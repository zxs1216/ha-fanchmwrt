"""The OpenWrt integration.

Provides deep integration with OpenWrt routers including:
- System monitoring (CPU, memory, storage, temperature)
- Network monitoring (interfaces, bandwidth, connected devices)
- Wireless management (WPS, radio control)
- Device tracking
- Firmware update detection (official & custom builds)
- Service management
- Remote commands
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import shutil
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .api.luci_rpc import LuciRpcAuthError, LuciRpcError
from .api.ssh import SshAuthError, SshError
from .api.ubus import UbusAuthError, UbusError
from .helpers.compact import (
    purge_aux_devices,
    purge_legacy_entities,
    purge_removed_entities,
    router_identifier_set,
)
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_OPENCLASH,
    DOMAIN,
    PLATFORMS,
    SERVICE_REBOOT,
)
from .coordinator import OpenWrtDataCoordinator, create_client
from .openclash import OpenClashCoordinator, openclash_device_id
from .services import register_services

_register_services = register_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

FRONTEND_ASSET = "fanchmwrt-overview.js"

type OpenWrtConfigEntry = ConfigEntry


def _publish_frontend_asset(hass: HomeAssistant) -> None:
    """把随包的 Lovelace 总览卡片发布到 /config/www，供仪表盘资源引用。"""
    source = Path(__file__).parent / "frontend" / FRONTEND_ASSET
    if not source.is_file():
        return
    target = Path(hass.config.path("www", FRONTEND_ASSET))
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.read_bytes() != source.read_bytes():
        shutil.copyfile(source, target)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up integration and publish the overview card asset."""
    try:
        await hass.async_add_executor_job(_publish_frontend_asset, hass)
    except Exception as err:  # noqa: BLE001 - 前端资源发布失败不影响集成功能
        _LOGGER.warning("发布 FanchmWrt 总览卡片资源失败: %s", err)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate entry."""
    _LOGGER.debug("Migrating from version %s", entry.version)

    if entry.version == 1:
        # Version 2 uses MAC address as unique_id instead of IP
        client = create_client(hass, dict(entry.data))
        try:
            await client.connect()
            device_info = await client.get_device_info()

            if device_info.mac_address:
                new_unique_id = dr.format_mac(device_info.mac_address)
                hass.config_entries.async_update_entry(
                    entry,
                    unique_id=new_unique_id,
                    version=2,
                )
                _LOGGER.info(
                    "Migrated OpenWrt entry %s to version 2 (MAC: %s)",
                    entry.entry_id,
                    new_unique_id,
                )
            else:
                hass.config_entries.async_update_entry(entry, version=2)
                _LOGGER.warning(
                    "Could not get MAC for %s migration. Version bumped.",
                    entry.entry_id,
                )
        except Exception as err:
            _LOGGER.exception("Migration failed for %s: %s", entry.entry_id, err)
            return False
        finally:
            await client.disconnect()

    return True


def _async_migrate_entity_units(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear stale unit_of_measurement overrides that came from old integration versions.

    When native_unit_of_measurement changes in code, Home Assistant may have
    the old unit cached as a registry override. Clearing these overrides forces
    HA to re-read the current unit from the entity on the next state write.
    """
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)

    # Keys whose units we have deliberately changed between versions.
    # Clearing the override (unit_of_measurement = None) makes HA use the
    # integration's native_unit_of_measurement again.
    stale_unit_keys = {
        # Uptime: was UnitOfTime.MINUTES, now UnitOfTime.SECONDS
        "_uptime",
        # Storage: was raw bytes (no explicit unit), now UnitOfInformation.MEGABYTES
        "_storage_free_",
        "_storage_used_",
        "_storage_total_",
        "_filesystem_free",
    }

    for ent in entries:
        if ent.domain != "sensor":
            continue
        uid = ent.unique_id or ""
        if any(key in uid for key in stale_unit_keys):
            # Only clear if there IS a stored override (unit_of_measurement != None)
            if ent.unit_of_measurement is not None:
                _LOGGER.debug(
                    "Clearing stale unit override '%s' for entity %s",
                    ent.unit_of_measurement,
                    ent.entity_id,
                )
                ent_reg.async_update_entity(
                    ent.entity_id,
                    unit_of_measurement=None,
                )


async def _async_cleanup_disabled_features(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove entities and devices from disabled features from registries."""
    from .const import (
        CONF_ENABLE_FIREWALL,
        CONF_ENABLE_LED,
        CONF_ENABLE_LOAD,
        CONF_ENABLE_NLBWMON_SENSORS,
        CONF_ENABLE_SERVICES,
        CONF_ENABLE_SNORT_SENSORS,
        CONF_ENABLE_SQM,
        CONF_ENABLE_VPN,
        CONF_TRACK_DEVICES,
        DEFAULT_TRACK_DEVICES,
    )

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    track_devices = entry.options.get(CONF_TRACK_DEVICES, DEFAULT_TRACK_DEVICES)
    enable_led = entry.options.get(CONF_ENABLE_LED, False)
    enable_firewall = entry.options.get(CONF_ENABLE_FIREWALL, False)
    enable_services = entry.options.get(CONF_ENABLE_SERVICES, False)
    enable_vpn = entry.options.get(CONF_ENABLE_VPN, False)
    enable_sqm = entry.options.get(CONF_ENABLE_SQM, False)
    enable_load = entry.options.get(CONF_ENABLE_LOAD, False)
    enable_nlbwmon = entry.options.get(CONF_ENABLE_NLBWMON_SENSORS, False)
    enable_snort = entry.options.get(CONF_ENABLE_SNORT_SENSORS, False)

    # 1. Clean up entities of disabled features
    entity_entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    for ent in entity_entries:
        should_remove = False
        ent_unique_id = ent.unique_id or ""

        if not track_devices:
            if (
                ent.domain == "device_tracker"
                or "_wol" in ent_unique_id
                or "_kick_" in ent_unique_id
                or "_access_" in ent_unique_id
            ):
                should_remove = True

        if not enable_led and "_led_" in ent_unique_id:
            should_remove = True

        if not enable_firewall and "_firewall_" in ent_unique_id:
            should_remove = True

        if not enable_services and "_service_" in ent_unique_id:
            should_remove = True

        if not enable_vpn and ("_wg_" in ent_unique_id or "_tsvpn_" in ent_unique_id):
            should_remove = True

        if not enable_sqm and "_sqm_" in ent_unique_id:
            should_remove = True

        if not enable_load and "_load_" in ent_unique_id:
            should_remove = True

        if not enable_nlbwmon and "_nlbwmon_" in ent_unique_id:
            should_remove = True

        if not enable_snort and "_snort_" in ent_unique_id:
            should_remove = True

        if should_remove:
            _LOGGER.info(
                "Removing entity %s of disabled feature (unique_id=%s)",
                ent.entity_id,
                ent_unique_id,
            )
            try:
                ent_reg.async_remove(ent.entity_id)
            except KeyError:
                pass

    # 2. Clean up device registry for tracked devices if device tracking is disabled
    if not track_devices:
        entry_unique_id = entry.unique_id
        if entry_unique_id and len(entry_unique_id.replace(":", "")) == 12:
            router_id = dr.format_mac(entry_unique_id)
        elif entry_unique_id:
            router_id = entry_unique_id
        else:
            router_id = str(entry.data[CONF_HOST])

        for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            is_router_or_ap = False
            for identifier in dev.identifiers:
                if identifier[0] == DOMAIN:
                    ident_str = str(identifier[1])
                    norm_ident = ident_str.replace(":", "").lower()
                    norm_router_id = (
                        router_id.replace(":", "").lower()
                        if isinstance(router_id, str)
                        else ""
                    )
                    norm_host = (
                        str(entry.data.get(CONF_HOST, "")).replace(":", "").lower()
                    )

                    if (
                        ident_str == router_id
                        or norm_ident == norm_router_id
                        or norm_ident == norm_host
                        or "_ap_" in ident_str
                        or "_ra" in ident_str
                    ):
                        is_router_or_ap = True
                        break
            if not is_router_or_ap:
                _LOGGER.info(
                    "Removing tracked client device %s (%s) because device tracking is disabled",
                    dev.name,
                    dev.id,
                )
                dev_reg.async_remove_device(dev.id)


def _ha_dashboard_url(hass: HomeAssistant, path: str) -> str:
    """生成指向 HA 内部总览页的绝对 URL。

    device registry 的 configuration_url 只接受绝对 URL，相对路径会抛 ValueError
    并导致整个集成 setup 失败，因此这里必须拿到 HA 自身的访问地址。
    """
    try:
        from homeassistant.helpers.network import get_url  # noqa: PLC0415

        base = get_url(hass)
    except Exception:  # noqa: BLE001
        base = ""
    if not base:
        base = hass.config.external_url or hass.config.internal_url or ""
    if not base:
        base = "http://127.0.0.1:8123"
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _async_register_v4_devices(
    hass: HomeAssistant, entry: ConfigEntry, openclash: OpenClashCoordinator
) -> None:
    """注册计划书要求的两个主条目，并挂上各自的「访问」链接。"""
    dev_reg = dr.async_get(hass)
    host = str(entry.data.get(CONF_HOST, ""))
    router_ident = str(entry.unique_id or host)

    # v4.2：两个设备的「访问」都指向 HA 内部的深色总览页，不跳任何外部站点
    router_url = _ha_dashboard_url(hass, "fanchmwrt-router")
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if (DOMAIN, router_ident) in device.identifiers:
            if device.configuration_url != router_url:
                dev_reg.async_update_device(
                    device.id,
                    configuration_url=router_url,
                )
            break

    status_url = _ha_dashboard_url(hass, "fanchmwrt-openclash")

    oc_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, openclash_device_id(entry))},
        name="OpenClash",
        manufacturer="FanchmWrt",
        model="Mihomo / OpenClash",
        configuration_url=status_url,
    )
    # async_get_or_create 不会覆盖已存在设备的 configuration_url，需显式更新
    if oc_device.configuration_url != status_url:
        dev_reg.async_update_device(oc_device.id, configuration_url=status_url)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    client = create_client(hass, {**entry.data, **entry.options})

    try:
        try:
            await client.connect()
        except (UbusAuthError, LuciRpcAuthError, SshAuthError) as err:
            msg = f"Authentication failed: {err}"
            raise ConfigEntryAuthFailed(msg) from err
        except (UbusError, LuciRpcError, SshError) as err:
            msg = f"Cannot connect to {entry.data[CONF_HOST]}: {err}"
            raise ConfigEntryNotReady(msg) from err

        coordinator = OpenWrtDataCoordinator(hass, entry, client)

        # Initialize coordinator data which also handles device registry updates
        await coordinator.async_config_entry_first_refresh()

        # v4: OpenClash 独立数据源，失败时只降级（不阻断集成加载）
        openclash = OpenClashCoordinator(hass, entry, client)
        await openclash.async_refresh()

        # Clear any stale unit_of_measurement overrides from previous versions
        _async_migrate_entity_units(hass, entry)

        # Clean up any entities or devices from disabled features
        await _async_cleanup_disabled_features(hass, entry)

        # 旁路由精简模式：清除历史遗留的无线 / 客户端辅助设备及其全部实体
        removed_aux = purge_aux_devices(
            hass, entry, router_identifier_set(entry, coordinator)
        )
        if removed_aux:
            _LOGGER.info("FanchmWrt: removed %s auxiliary devices", removed_aux)

        # 旁路由精简模式：清除已移除功能类别的遗留实体
        removed_entities = purge_removed_entities(hass, entry)
        if removed_entities:
            _LOGGER.info(
                "FanchmWrt: removed %s obsolete entities", removed_entities
            )

        # v4: 清除旧 openwrt 集成与历史精简留下的全部禁用实体 / 设备
        legacy_entities, legacy_devices = purge_legacy_entities(hass, entry)
        if legacy_entities or legacy_devices:
            _LOGGER.info(
                "FanchmWrt v4: purged %s legacy entities and %s legacy devices",
                legacy_entities,
                legacy_devices,
            )

        # v4: 两个主条目（路由器 / OpenClash）各自的「访问」链接
        _async_register_v4_devices(hass, entry, openclash)

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {
            DATA_COORDINATOR: coordinator,
            DATA_CLIENT: client,
            DATA_OPENCLASH: openclash,
        }

        # Pre-import platforms in the background to avoid blocking the event loop
        # during async_forward_entry_setups which calls sync import_module
        async def _import_platform(platform: str) -> None:
            try:
                await hass.async_add_import_executor_job(
                    importlib.import_module,
                    f"custom_components.{DOMAIN}.{platform}",
                )
            except Exception:
                _LOGGER.debug("Could not pre-import platform %s", platform)

        await asyncio.gather(*(_import_platform(platform) for platform in PLATFORMS))

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # v4.0.2：平台实体是异步注册的，延迟几秒再兜底清一次
        async def _async_late_purge() -> None:
            await asyncio.sleep(4)
            late_entities, late_devices = purge_legacy_entities(hass, entry)
            if late_entities or late_devices:
                _LOGGER.info(
                    "FanchmWrt v4: purged %s disabled entities after platform setup",
                    late_entities,
                )

        hass.async_create_task(_async_late_purge())

        if not hass.services.has_service(DOMAIN, SERVICE_REBOOT):
            register_services(hass)

        entry.async_on_unload(entry.add_update_listener(_async_update_listener))

        return True
    except Exception:
        await client.disconnect()
        raise


async def async_unload_entry(hass: HomeAssistant, entry: OpenWrtConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator: OpenWrtDataCoordinator = entry_data[DATA_COORDINATOR]
        await coordinator.async_shutdown()

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: OpenWrtConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removing a device this entry no longer provides.

    Refuses the router itself, its current radio and SSID devices, any client the
    entry is tracking right now, and any device that still carries one of this
    entry's entities -- those would be recreated on the next poll, or lose a live
    entity until the entry is reloaded.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not entry_data:
        return True
    coordinator: OpenWrtDataCoordinator = entry_data[DATA_COORDINATOR]

    if device_entry.identifiers & coordinator.active_device_identifiers:
        return False

    # An offline client keeps its tracker (whitelisted, or remembered in the
    # device history), so being absent from the poll does not make it stale.
    ent_reg = er.async_get(hass)
    if any(
        ent.config_entry_id == entry.entry_id
        for ent in er.async_entries_for_device(
            ent_reg, device_entry.id, include_disabled_entities=True
        )
    ):
        return False

    if coordinator.data:
        tracked_macs = {
            d.mac.lower() for d in coordinator.data.connected_devices if d.mac
        }
        tracked_macs.update(
            lease.mac.lower() for lease in coordinator.data.dhcp_leases if lease.mac
        )
        if any(
            ident[0] == DOMAIN and str(ident[1]).lower() in tracked_macs
            for ident in device_entry.identifiers
        ):
            return False

    return True


async def _async_update_listener(
    hass: HomeAssistant,
    entry: OpenWrtConfigEntry,
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
