"""Sensor platform for OpenWrt integration.

Provides comprehensive system, network, and wireless monitoring sensors.
All entities are grouped under the router device.
"""

from __future__ import annotations

from .helpers.compact import filter_router_only, router_identifier_set

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENABLE_LOAD,
    CONF_ENABLE_NLBWMON_SENSORS,
    CONF_ENABLE_SNORT_SENSORS,
    CONF_ENABLE_VPN,
    CONF_SKIP_RANDOM_MAC,
    CONF_TRACK_DEVICES,
    CONF_TRACK_WIRED,
    DATA_COORDINATOR,
    DEFAULT_SKIP_RANDOM_MAC,
    DEFAULT_TRACK_DEVICES,
    DEFAULT_TRACK_WIRED,
    DOMAIN,
)
from .coordinator import OpenWrtDataCoordinator
from .helpers import is_random_mac
from .sensors import (
    OpenWrtDeviceSensor,
    OpenWrtMwanMetricSensor,
    OpenWrtNlbwmonRxSensor,
    OpenWrtNlbwmonTopHostsSensor,
    OpenWrtNlbwmonTxSensor,
    OpenWrtQModemSensorEntity,
    OpenWrtSensorDescription,
    OpenWrtSensorEntity,
    OpenWrtSnortSensor,
    OpenWrtStorageSensor,
    OpenWrtStorageSensorDescription,
    OpenWrtTemperatureSensor,
    OpenWrtWifiSensorEntity,
    OpenWrtWireGuardPeerSensor,
    _async_setup_network_sensors,
    _async_setup_specialized_sensors,
    _async_setup_storage_sensors,
    _async_setup_system_sensors,
    _async_setup_tailscale_sensors,
    _async_setup_wireguard_sensors,
    _async_setup_wireless_sensors,
    _bytes_to_mb,
    _create_batman_neighbor_sensors,
    _create_device_sensors,
    _create_lldp_sensors,
    _create_mwan_sensors,
    _create_net_address_sensors,
    _create_net_rate_sensors,
    _create_net_sensors,
    _create_net_status_sensors,
    _create_net_traffic_sensors,
    _create_nlbwmon_sensors,
    _create_sqm_sensors,
    _create_vpn_sensors,
    _create_wifi_base_sensors,
    _create_wifi_sensors,
    _create_wifi_station_sensors,
    _format_bytes,
    _get_adblock_sensors,
    _get_banip_sensors,
    _get_batman_global_sensors,
    _get_device_display_name,
    _get_qmodem_sensors,
    _get_simple_adblock_sensors,
    _get_system_sensors,
    _get_upnp_sensors,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "DeviceInfo",
    "OpenWrtDeviceSensor",
    "OpenWrtMwanMetricSensor",
    "OpenWrtNlbwmonRxSensor",
    "OpenWrtNlbwmonTopHostsSensor",
    "OpenWrtNlbwmonTxSensor",
    "OpenWrtQModemSensorEntity",
    "OpenWrtSensorDescription",
    "OpenWrtSensorEntity",
    "OpenWrtSnortSensor",
    "OpenWrtStorageSensor",
    "OpenWrtStorageSensorDescription",
    "OpenWrtTemperatureSensor",
    "OpenWrtWifiSensorEntity",
    "OpenWrtWireGuardPeerSensor",
    "_async_setup_network_sensors",
    "_async_setup_specialized_sensors",
    "_async_setup_storage_sensors",
    "_async_setup_system_sensors",
    "_async_setup_tailscale_sensors",
    "_async_setup_wireguard_sensors",
    "_async_setup_wireless_sensors",
    "_bytes_to_mb",
    "_create_batman_neighbor_sensors",
    "_create_device_sensors",
    "_create_lldp_sensors",
    "_create_mwan_sensors",
    "_create_net_address_sensors",
    "_create_net_rate_sensors",
    "_create_net_sensors",
    "_create_net_status_sensors",
    "_create_net_traffic_sensors",
    "_create_nlbwmon_sensors",
    "_create_sqm_sensors",
    "_create_vpn_sensors",
    "_create_wifi_base_sensors",
    "_create_wifi_sensors",
    "_create_wifi_station_sensors",
    "_format_bytes",
    "_get_adblock_sensors",
    "_get_banip_sensors",
    "_get_batman_global_sensors",
    "_get_device_display_name",
    "_get_qmodem_sensors",
    "_get_simple_adblock_sensors",
    "_get_system_sensors",
    "_get_upnp_sensors",
    "async_setup_entry",
    "dt_util",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenWrt sensors from a config entry."""
    coordinator: OpenWrtDataCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]

    tracked_keys: set[str] = set()

    @callback
    def _async_discover_entities() -> None:
        """Discover and add all sensors (static and dynamic)."""
        if not coordinator.data:
            return

        new_entities: list[SensorEntity] = []
        perms = coordinator.data.permissions
        pkgs = coordinator.data.packages

        _LOGGER.debug(
            "Discovering sensors for %s. Permissions: %s, Packages: %s",
            entry.title,
            perms,
            pkgs,
        )

        # System & Storage Sensors
        _async_setup_system_sensors(
            coordinator,
            entry,
            new_entities,
            pkgs,
            tracked_keys,
            entry.options.get(CONF_ENABLE_LOAD, True),
        )
        _async_setup_storage_sensors(coordinator, entry, new_entities, tracked_keys)

        # 旁路由精简：VPN（WireGuard/Tailscale/OpenVPN）、无线、
        # MWAN/SQM/调制解调器等专用传感器已移除，仅保留系统 / 存储 / 网络
        _async_setup_network_sensors(
            coordinator, entry, new_entities, pkgs, tracked_keys
        )

        # 旁路由精简：按客户端的信号 / 速率 / NLBWmon 传感器已移除

        if new_entities:
            async_add_entities(
                filter_router_only(new_entities, router_identifier_set(entry, coordinator))
            )

    # Initial discovery and listener registration
    _async_discover_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_discover_entities))

    @callback
    def _async_cleanup_entities() -> None:
        """Clean up orphaned or old-format entities."""
        ent_reg = er.async_get(hass)
        entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)

        track_devices = entry.options.get(
            CONF_TRACK_DEVICES,
            entry.data.get(CONF_TRACK_DEVICES, DEFAULT_TRACK_DEVICES),
        )
        track_wired = entry.options.get(
            CONF_TRACK_WIRED,
            entry.data.get(CONF_TRACK_WIRED, DEFAULT_TRACK_WIRED),
        )

        for ent in entries:
            if ent.domain != "sensor":
                continue

            unique_id = ent.unique_id

            # Cleanup by settings
            if "_device_" in unique_id:
                if not track_devices:
                    ent_reg.async_remove(ent.entity_id)
                    continue

                # Identify MAC from unique_id
                parts = unique_id.split("_")
                if len(parts) >= 4:
                    mac = parts[1]
                    # Pattern check for old format
                    if f"_device_{mac}_" in unique_id:
                        ent_reg.async_remove(ent.entity_id)
                        continue

                    # Wired cleanup
                    if not track_wired and mac in coordinator._device_history:
                        if not coordinator._device_history[mac].get("is_wireless"):
                            ent_reg.async_remove(ent.entity_id)
                            continue

            # Cleanup top bandwidth hosts sensor when option is disabled
            if (
                unique_id == f"{entry.entry_id}_top_bandwidth_hosts"
                and not entry.options.get(
                    CONF_ENABLE_NLBWMON_SENSORS,
                    entry.data.get(CONF_ENABLE_NLBWMON_SENSORS, False),
                )
            ):
                ent_reg.async_remove(ent.entity_id)
                continue

            # Cleanup Snort alerts sensor when option is disabled
            if unique_id == f"{entry.entry_id}_snort_alerts" and not entry.options.get(
                CONF_ENABLE_SNORT_SENSORS,
                entry.data.get(CONF_ENABLE_SNORT_SENSORS, False),
            ):
                ent_reg.async_remove(ent.entity_id)
                continue

            # Cleanup Batman neighbors
            if "batman_neighbor_" in unique_id:
                current_keys = {
                    f"batman_neighbor_{n.mac}"
                    for n in coordinator.data.batman_neighbors
                }
                if unique_id not in current_keys:
                    ent_reg.async_remove(ent.entity_id)
                    tracked_keys.discard(unique_id)
                    continue

            # Cleanup orphaned wireless sensors (e.g. ghost placeholders) only when discovery is complete.
            # Only unconfigured ghost placeholders are pruned; legitimate entities are preserved during
            # partial reboots, dynamic DFS scans, or temporary interface omissions.
            if (
                "_wifi_" in unique_id
                and coordinator.data
                and coordinator.data.wireless_interfaces is not None
                and len(coordinator.data.wireless_interfaces) > 0
            ):
                # Extract the interface/section part from unique_id: {entry_id}_wifi_{iface_key}_{metric}
                parts = unique_id.split("_wifi_", 1)
                iface_key = parts[1].rsplit("_", 1)[0] if len(parts) == 2 else ""
                is_ghost_sensor = iface_key == "ghost" or iface_key.startswith("ghost_")
                if not is_ghost_sensor:
                    continue
                found = False
                for w in coordinator.data.wireless_interfaces:
                    if (
                        f"_wifi_{w.name}_" in unique_id
                        or (w.section and f"_wifi_{w.section}_" in unique_id)
                        or (w.ifname and f"_wifi_{w.ifname}_" in unique_id)
                        or (w.radio and f"_wifi_{w.radio}_" in unique_id)
                        or (w.ssid and f"_{w.ssid}_" in unique_id)
                        or (w.ssid and unique_id.endswith(f"_{w.ssid}"))
                    ):
                        found = True
                        break
                if not found:
                    _LOGGER.warning(
                        "Removing orphaned wireless sensor entity %s (unique_id=%s)",
                        ent.entity_id,
                        unique_id,
                    )
                    ent_reg.async_remove(ent.entity_id)
                    tracked_keys.discard(unique_id)
                    continue

            # Cleanup orphaned network address sensors for physical devices, removed interfaces, or interfaces without an IP
            if unique_id.startswith(f"{entry.entry_id}_net_") and coordinator.data:
                if unique_id.endswith("_ipv4"):
                    matched_iface = next(
                        (
                            i
                            for i in coordinator.data.network_interfaces
                            if f"_net_{i.name}_ipv4" in unique_id
                        ),
                        None,
                    )
                    if not matched_iface or not matched_iface.ipv4_address:
                        ent_reg.async_remove(ent.entity_id)
                        continue
                elif unique_id.endswith("_ipv6"):
                    matched_iface = next(
                        (
                            i
                            for i in coordinator.data.network_interfaces
                            if f"_net_{i.name}_ipv6" in unique_id
                        ),
                        None,
                    )
                    if not matched_iface or not matched_iface.ipv6_address:
                        ent_reg.async_remove(ent.entity_id)
                        continue

    hass.add_job(_async_cleanup_entities)

    # 旁路由精简：NLBWmon Top Hosts / SNORT 告警传感器已移除
