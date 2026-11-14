"""旁路由精简模式：只保留路由器主设备及其直接附属实体。

FanchmWrt 部署在旁路由上，不提供无线接入、不做客户端设备追踪。
上游代码仍会为 radio / SSID / 客户端 MAC 创建独立设备与实体，
这里在注册前统一过滤，并清理注册表中已有的辅助设备。
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr


def router_identifier_set(entry: ConfigEntry, coordinator: Any) -> set[str]:
    """返回路由器主设备在 device registry 中使用的全部标识符（小写）。"""
    candidates = (
        getattr(coordinator, "router_id", None),
        entry.unique_id,
        entry.data.get("host"),
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
