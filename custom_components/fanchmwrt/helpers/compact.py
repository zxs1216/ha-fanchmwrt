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
