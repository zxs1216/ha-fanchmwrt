"""Entities for the two FanchmWrt main entries (v4).

- Router 条目：控制 / 传感器 / 诊断三块；诊断块新增外网连通、网关延迟、DNS 耗时。
- OpenClash 条目：代理（分流组节点选择、刷新 DNS 缓存）、运行状态、流量、DNS 健康。

实体名直接使用中文，避免翻译键缺失造成英文回退。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.button import ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from .coordinator import SELECTABLE_GROUPS, OpenClashCoordinator, OpenClashData


def openclash_device_id(entry: ConfigEntry) -> str:
    """OpenClash 设备在 device registry 中使用的标识符。"""
    return f"{entry.data.get(CONF_HOST, 'router')}_openclash"


def group_entity_id(group: str) -> str:
    """把带 emoji 的组名转成稳定的 unique_id 片段。"""
    return hashlib.sha1(group.encode("utf-8")).hexdigest()[:10]


def _device_info(entry: ConfigEntry, target: str) -> DeviceInfo:
    if target == "openclash":
        return DeviceInfo(
            identifiers={(DOMAIN, openclash_device_id(entry))},
            name="OpenClash",
            manufacturer="FanchmWrt",
            model="Mihomo / OpenClash",
        )
    return DeviceInfo(
        identifiers={(DOMAIN, str(entry.unique_id or entry.data.get(CONF_HOST)))},
    )


class FanchmWrtOcEntity(CoordinatorEntity[OpenClashCoordinator]):
    """共用基类：绑定设备、生成 unique_id、统一可用性判断。"""

    _attr_has_entity_name = True
    _require_api = True

    def __init__(
        self,
        coordinator: OpenClashCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        target: str = "openclash",
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = _device_info(entry, target)

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        if not self.coordinator.last_update_success or data is None:
            return False
        if self._require_api:
            return bool(data.proxies)
        return True


class FanchmWrtOpenClashSensor(FanchmWrtOcEntity, SensorEntity):
    """OpenClash / 诊断数值型实体。"""

    def __init__(
        self,
        coordinator: OpenClashCoordinator,
        entry: ConfigEntry,
        *,
        key: str,
        name: str,
        value_fn: Callable[[OpenClashData], StateType],
        unit: str | None = None,
        icon: str | None = None,
        category: EntityCategory | None = None,
        target: str = "openclash",
        require_api: bool = True,
        attrs_fn: Callable[[OpenClashData], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(coordinator, entry, key, name, target)
        self._value_fn = value_fn
        self._attrs_fn = attrs_fn
        self._require_api = require_api
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_entity_category = category

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is None:
            return None
        return self._value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None or self._attrs_fn is None:
            return None
        return self._attrs_fn(self.coordinator.data)


class FanchmWrtOpenClashBinarySensor(FanchmWrtOcEntity, BinarySensorEntity):
    """OpenClash / 诊断布尔型实体。"""

    def __init__(
        self,
        coordinator: OpenClashCoordinator,
        entry: ConfigEntry,
        *,
        key: str,
        name: str,
        is_on_fn: Callable[[OpenClashData], bool],
        device_class: BinarySensorDeviceClass | None = None,
        category: EntityCategory | None = EntityCategory.DIAGNOSTIC,
        target: str = "openclash",
        require_api: bool = True,
    ) -> None:
        super().__init__(coordinator, entry, key, name, target)
        self._is_on_fn = is_on_fn
        self._require_api = require_api
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        return self._is_on_fn(self.coordinator.data)


class FanchmWrtOpenClashButton(FanchmWrtOcEntity, ButtonEntity):
    """OpenClash 控制块按钮。"""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: OpenClashCoordinator,
        entry: ConfigEntry,
        *,
        key: str,
        name: str,
        icon: str = "mdi:refresh",
    ) -> None:
        super().__init__(coordinator, entry, key, name, "openclash")
        self._attr_icon = icon

    async def async_press(self) -> None:
        await self.coordinator.client.async_flush_dns_cache()
        await self.coordinator.async_request_refresh()


class FanchmWrtOpenClashSelect(FanchmWrtOcEntity, SelectEntity):
    """分流组当前节点选择。"""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:server-network"

    def __init__(
        self,
        coordinator: OpenClashCoordinator,
        entry: ConfigEntry,
        group: str,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            f"oc_group_{group_entity_id(group)}",
            f"{group} 节点",
            "openclash",
        )
        self._group = group

    @property
    def options(self) -> list[str]:
        data = self.coordinator.data
        options = list(((data.groups.get(self._group) or {}).get("all") or [])) if data else []
        return options or ["—"]

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        return (data.groups.get(self._group) or {}).get("now")

    async def async_select_option(self, option: str) -> None:
        if option not in self.options or option == "—":
            return
        await self.coordinator.client.async_select_node(self._group, option)
        await self.coordinator.async_request_refresh()


def openclash_sensors(
    coordinator: OpenClashCoordinator, entry: ConfigEntry
) -> list[FanchmWrtOpenClashSensor]:
    """OpenClash 条目：运行状态与流量部分。"""
    gb = 1024**3
    kb = 1024
    return [
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_sub_remaining", name="剩余流量",
            value_fn=lambda d: d.sub_remaining, unit="GB",
            icon="mdi:gauge", require_api=False,
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_sub_total", name="套餐总流量",
            value_fn=lambda d: d.sub_total, unit="GB",
            icon="mdi:database", require_api=False,
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_sub_used", name="已用流量",
            value_fn=lambda d: d.sub_used, unit="GB",
            icon="mdi:chart-bar", require_api=False,
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_sub_percent", name="流量使用率",
            value_fn=lambda d: d.sub_percent, unit="%",
            icon="mdi:percent", require_api=False,
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_current_node", name="当前节点",
            value_fn=lambda d: d.current_node, icon="mdi:server-network",
            attrs_fn=lambda d: {
                "分流组": "🚀 节点选择",
                "模式": d.mode,
                "活动连接": d.connections,
            },
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_up_rate", name="实时上传",
            value_fn=lambda d: round(d.up_rate / kb, 1),
            unit="kB/s", icon="mdi:upload",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_down_rate", name="实时下载",
            value_fn=lambda d: round(d.down_rate / kb, 1),
            unit="kB/s", icon="mdi:download",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_up_total", name="累计上传",
            value_fn=lambda d: round(d.up_total / gb, 2),
            unit="GB", icon="mdi:upload-network",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_down_total", name="累计下载",
            value_fn=lambda d: round(d.down_total / gb, 2),
            unit="GB", icon="mdi:download-network",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_proxy_total", name="代理累计流量",
            value_fn=lambda d: round((d.up_total + d.down_total) / gb, 2),
            unit="GB", icon="mdi:chart-areaspline",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_connections", name="活动连接数",
            value_fn=lambda d: d.connections, icon="mdi:lan-connect",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_rules", name="规则数",
            value_fn=lambda d: d.rules, category=EntityCategory.DIAGNOSTIC,
            icon="mdi:file-document-multiple",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_dns_latency", name="DNS 解析延迟",
            value_fn=lambda d: d.dns_latency, unit="ms",
            category=EntityCategory.DIAGNOSTIC, require_api=False,
            icon="mdi:dns",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_version", name="内核版本",
            value_fn=lambda d: d.version, category=EntityCategory.DIAGNOSTIC,
            icon="mdi:information-outline",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="oc_mode", name="代理模式",
            value_fn=lambda d: d.mode, category=EntityCategory.DIAGNOSTIC,
            icon="mdi:swap-horizontal",
        ),
    ]


def openclash_binary_sensors(
    coordinator: OpenClashCoordinator, entry: ConfigEntry
) -> list[FanchmWrtOpenClashBinarySensor]:
    return [
        FanchmWrtOpenClashBinarySensor(
            coordinator, entry,
            key="oc_running", name="OpenClash 运行",
            is_on_fn=lambda d: bool(d.proxies),
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
        ),
        FanchmWrtOpenClashBinarySensor(
            coordinator, entry,
            key="oc_dns_healthy", name="DNS 解析健康",
            is_on_fn=lambda d: d.dns_ok,
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            require_api=False,
        ),
    ]


def openclash_buttons(
    coordinator: OpenClashCoordinator, entry: ConfigEntry
) -> list[FanchmWrtOpenClashButton]:
    return [
        FanchmWrtOpenClashButton(
            coordinator, entry,
            key="oc_flush_dns", name="刷新 DNS 缓存", icon="mdi:refresh",
        )
    ]


def openclash_selects(
    coordinator: OpenClashCoordinator, entry: ConfigEntry
) -> list[FanchmWrtOpenClashSelect]:
    return [
        FanchmWrtOpenClashSelect(coordinator, entry, group)
        for group in SELECTABLE_GROUPS
    ]


def build_router_diagnostics(
    coordinator: OpenClashCoordinator, entry: ConfigEntry
) -> list[FanchmWrtOcEntity]:
    """Router 条目诊断块：连网状态、网关与 DNS 时延。"""
    return [
        FanchmWrtOpenClashBinarySensor(
            coordinator, entry,
            key="diag_internet", name="外网连通",
            is_on_fn=lambda d: d.internet_ok,
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            target="router", require_api=False,
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="diag_gateway_latency", name="网关延迟",
            value_fn=lambda d: d.gateway_latency, unit="ms",
            category=EntityCategory.DIAGNOSTIC,
            target="router", require_api=False, icon="mdi:router-network",
        ),
        FanchmWrtOpenClashSensor(
            coordinator, entry,
            key="diag_dns_latency", name="DNS 解析耗时",
            value_fn=lambda d: d.dns_latency, unit="ms",
            category=EntityCategory.DIAGNOSTIC,
            target="router", require_api=False, icon="mdi:dns",
        ),
    ]
