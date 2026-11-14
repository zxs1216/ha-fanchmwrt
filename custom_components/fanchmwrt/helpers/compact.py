"""旁路由精简模式：只保留路由器主设备及其直接附属实体。

FanchmWrt 部署在旁路由上，不提供无线接入、不做客户端设备追踪。
上游代码仍会为 radio / SSID / 客户端 MAC 创建独立设备与实体，
这里在注册前统一过滤，并清理注册表中已有的辅助设备。
"""

from __future__ import annotations

import contextlib
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr


def router_identifier_set(entry: ConfigEntry, coordinator: Any) -> set[str]:
    """返回 v4 允许保留的设备标识符（路由器主设备 + OpenClash 主设备）。"""
    host = entry.data.get("host")
    candidates = (
        getattr(coordinator, "router_id", None),
        entry.unique_id,
        host,
        f"{host}_openclash" if host else None,
    )
    return {str(value).lower() for value in candidates if value}


def filter_router_only(entities: list[Any], allowed: set[str]) -> list[Any]:
    """丢弃声明了「非路由器设备」的实体，保留主设备与无设备声明的实体。"""
    result: list[Any] = []
    for entity in entities:
        info = getattr(entity, "device_info", None)
        if callable(info):
            try:
                info = info()
            except Exception:  # noqa: BLE001 - 属性实现差异，保守保留
                result.append(entity)
                continue
        if not isinstance(info, dict):
            result.append(entity)
            continue

        identifiers = info.get("identifiers") or ()
        values = {
            str(item[1]).lower()
            for item in identifiers
            if isinstance(item, (tuple, list)) and len(item) > 1
        }
        if not values or values & allowed:
            result.append(entity)
    return result


# 服务状态 / 服务启停按钮与开关：计划书三大块不需要，从源头不创建。
V4_SERVICE_ENTITY_PREFIXES: tuple[str, ...] = (
    "service_",
    "restart_",
    "stop_",
    "start_",
    "reload_",
)


def filter_v4_entities(entities: list[Any]) -> list[Any]:
    """v4：清除服务类实体，并把计划书需要的传感器从「默认禁用」改为「默认启用」。

    上游把存储 / 接口速率 / 系统日志 / 进程排行等实体设为
    entity_registry_enabled_default=False，于是设备页出现
    「+N 个已禁用实体」。计划书要求这些属于传感器块，因此强制启用；
    只有成批的服务控制实体被丢弃。
    """
    result: list[Any] = []
    for entity in entities:
        unique_id = str(getattr(entity, "_attr_unique_id", "") or "").lower()
        tail = unique_id.split("_", 1)[-1] if "_" in unique_id else unique_id
        if tail.startswith(V4_SERVICE_ENTITY_PREFIXES):
            continue

        if getattr(entity, "_attr_entity_registry_enabled_default", True) is False:
            entity._attr_entity_registry_enabled_default = True
        description = getattr(entity, "entity_description", None)
        if description is not None and (
            getattr(description, "entity_registry_enabled_default", True) is False
        ):
            # EntityDescription 是 frozen dataclass，需要绕过冻结赋值
            with contextlib.suppress(Exception):
                object.__setattr__(
                    description, "entity_registry_enabled_default", True
                )
        result.append(entity)
    return result


def purge_aux_devices(hass: Any, entry: ConfigEntry, allowed: set[str]) -> int:
    """删除该集成条目下除路由器主设备之外的所有设备（连带其实体）。"""
    registry = dr.async_get(hass)
    removed = 0
    for device in list(dr.async_entries_for_config_entry(registry, entry.entry_id)):
        values = {
            str(item[1]).lower()
            for item in device.identifiers
            if isinstance(item, (tuple, list)) and len(item) > 1
        }
        if values & allowed:
            continue
        registry.async_remove_device(device.id)
        removed += 1
    return removed


# 旁路由精简模式下不再创建的实体，其 unique_id 片段。
# 用于清理注册表中历史遗留的同名实体（restored 实体不会自动消失）。
REMOVED_ENTITY_PATTERNS: tuple[str, ...] = (
    "_wps",
    "_create_backup",
    "_public_ip",
    "_wireless_clients",
    "_neighbor_devices",
    "_wg_",  # WireGuard 接口与 peer
    "_tsvpn_",  # Tailscale
    "_vpn_",  # OpenVPN / VPN 接口状态
    "_sqm_",
    "_led_",
    "_qmodem",
    "_mwan_",
    "_mesh_",
    "batman",
    "_nlbwmon_",
    "top_bandwidth_hosts",
    "_snort_alerts",
    "_adblock",
    "_simple_adblock",
    "_banip",
    "_access_",
    "_wireless_",
    "_radio_",
    "_wol",
    "_kick_",
    "_lldp_",
    "_mqtt_presence_status",
    "_dhcp_lease_count",
    "_swap_usage",
)


def purge_removed_entities(hass: Any, entry: ConfigEntry) -> int:
    """删除注册表中属于已移除功能类别的实体。"""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    registry = er.async_get(hass)
    removed = 0
    for entity in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
        unique_id = (entity.unique_id or "").lower()
        if any(pattern in unique_id for pattern in REMOVED_ENTITY_PATTERNS):
            registry.async_remove(entity.entity_id)
            removed += 1
    return removed


def purge_legacy_entities(hass: Any, entry: ConfigEntry) -> tuple[int, int]:
    """v4 一次性迁移：彻底清除旧集成与历史版本留下的禁用实体。

    返回 (删除的实体数, 删除的设备数)。三类目标：
    1. platform=openwrt 的全部实体（旧 ha-openwrt 集成残留，含 config_entry/user 禁用项）
    2. 本条目下任何被禁用的实体（历次精简后残留的「已禁用实体」）
    3. identifiers 属于旧 openwrt 域的设备（连同其实体）
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    removed_entities = 0

    # 用官方 helper 遍历本条目：HA 2026 里 registry.entities 的直接迭代
    # 已被弃用且行为不稳定，这里必须走 async_entries_for_config_entry。
    for entity in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        unique_id = (entity.unique_id or "").lower()
        tail = unique_id.split("_", 1)[-1] if "_" in unique_id else unique_id
        # 禁用项 + 服务控制类僵尸项一律删除；保留项会在本次以「默认启用」重新注册
        if (
            getattr(entity, "disabled_by", None) is not None
            or tail.startswith(V4_SERVICE_ENTITY_PREFIXES)
        ):
            try:
                ent_reg.async_remove(entity.entity_id)
                removed_entities += 1
            except (KeyError, ValueError):
                pass

    # 跨条目的旧版 openwrt 集成残留
    for entity in list(ent_reg.entities.values()):
        if getattr(entity, "platform", None) == "openwrt":
            try:
                ent_reg.async_remove(entity.entity_id)
                removed_entities += 1
            except (KeyError, ValueError):
                pass

    removed_devices = 0
    # 使用官方 helper 迭代，避免触发 device_registry.devices 的弃用告警
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if any(
            isinstance(item, (tuple, list)) and len(item) > 1 and item[0] == "openwrt"
            for item in device.identifiers
        ):
            # 旧设备可能仍挂着本条目新实体，只在没有实体时删除
            if not er.async_entries_for_device(ent_reg, device.id, include_disabled_entities=True):
                try:
                    dev_reg.async_remove_device(device.id)
                    removed_devices += 1
                except (KeyError, ValueError):
                    pass

    return removed_entities, removed_devices
