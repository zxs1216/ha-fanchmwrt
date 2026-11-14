"""FanchmWrt v4: OpenClash / mihomo platform.

按计划书拆出的第二个主条目：代理、运行状态、流量、DNS 健康。
数据源为路由器上 mihomo 的 RESTful API（默认 9090）。
"""

from .api import MihomoClient, probe_dns, probe_tcp
from .coordinator import OpenClashCoordinator, OpenClashData
from .entities import (
    FanchmWrtOpenClashBinarySensor,
    FanchmWrtOpenClashButton,
    FanchmWrtOpenClashSelect,
    FanchmWrtOpenClashSensor,
    build_router_diagnostics,
    group_entity_id,
    openclash_binary_sensors,
    openclash_device_id,
    openclash_buttons,
    openclash_selects,
    openclash_sensors,
)

__all__ = [
    "FanchmWrtOpenClashBinarySensor",
    "FanchmWrtOpenClashButton",
    "FanchmWrtOpenClashSelect",
    "FanchmWrtOpenClashSensor",
    "MihomoClient",
    "OpenClashCoordinator",
    "OpenClashData",
    "build_router_diagnostics",
    "group_entity_id",
    "openclash_binary_sensors",
    "openclash_device_id",
    "openclash_buttons",
    "openclash_selects",
    "openclash_sensors",
    "probe_dns",
    "probe_tcp",
]
