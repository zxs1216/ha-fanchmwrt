"""OpenClash / mihomo data coordinator."""

from __future__ import annotations

import logging
from asyncio import Task
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..const import (
    CONF_MIHOMO_PORT,
    CONF_MIHOMO_SECRET,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_MIHOMO_PORT,
)
from .api import MihomoClient, probe_dns, probe_tcp
from .subscription import Subscription, async_fetch_subscriptions

_LOGGER = logging.getLogger(__name__)

# 计划书中需要独立控制的五个分流组
SELECTABLE_GROUPS: tuple[str, ...] = (
    "🚀 节点选择",
    "🎯 Gemini",
    "🎯 TikTok",
    "🎯 Discord",
    "🎯 X",
)

MAIN_GROUP = "🚀 节点选择"


@dataclass
class OpenClashData:
    """一次轮询得到的 OpenClash 与网络诊断快照。"""

    proxies: dict[str, dict[str, Any]] = field(default_factory=dict)
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_node: str | None = None
    version: str | None = None
    mode: str | None = None
    up_rate: int = 0
    down_rate: int = 0
    up_total: int = 0
    down_total: int = 0
    connections: int = 0
    rules: int = 0
    dns_ok: bool = False
    dns_latency: float | None = None
    internet_ok: bool = False
    gateway_latency: float | None = None
    # 订阅套餐流量（GB）
    sub_total: float | None = None
    sub_used: float | None = None
    sub_remaining: float | None = None
    sub_percent: float | None = None
    subscriptions: tuple[Subscription, ...] = ()


class OpenClashCoordinator(DataUpdateCoordinator[OpenClashData]):
    """轮询 mihomo API，失败时只降级、不阻断整个集成加载。"""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, router_client: Any
    ) -> None:
        host = str(entry.data.get(CONF_HOST, ""))
        port = int(entry.options.get(CONF_MIHOMO_PORT, DEFAULT_MIHOMO_PORT))
        secret = str(entry.options.get(CONF_MIHOMO_SECRET, "") or "")
        self.client = MihomoClient(hass, host, port, secret)
        self.router_client = router_client
        self._ssh = {
            "host": host,
            "username": str(entry.data.get(CONF_USERNAME, "root")),
            "password": str(entry.data.get(CONF_PASSWORD, "") or ""),
        }
        self._entry = entry
        self.host = host
        self.port = port
        self.secret = secret
        self._slow_tick = 0
        self._rules = 0
        self._version: str | None = None
        self._mode: str | None = None
        self._subscriptions: tuple[Subscription, ...] = ()
        self._subscription_task: Task[None] | None = None
        self._next_subscription_check = 0.0
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="FanchmWrt OpenClash",
            update_interval=timedelta(seconds=15),
        )

    async def _async_refresh_subscriptions(self) -> None:
        subscriptions = await async_fetch_subscriptions(
            self.hass, self.router_client, self._ssh
        )
        if subscriptions is not None:
            self._subscriptions = subscriptions
        self._next_subscription_check = monotonic() + (60 if subscriptions is None else 600)

    async def _async_update_data(self) -> OpenClashData:
        if monotonic() >= self._next_subscription_check and (
            self._subscription_task is None or self._subscription_task.done()
        ):
            self._subscription_task = self._entry.async_create_background_task(
                self.hass, self._async_refresh_subscriptions(), "OpenClash subscriptions"
            )
        data = OpenClashData(subscriptions=self._subscriptions)
        # 原有实体继续表示当前配置，避免自动化读到另一份套餐。
        traffic = next(
            (sub.traffic for sub in data.subscriptions if sub.active and sub.traffic),
            None,
        )
        if traffic:
            data.sub_total = traffic.total
            data.sub_used = traffic.used
            data.sub_remaining = traffic.remaining
            data.sub_percent = traffic.percent

        # 诊断探测在 executor 中执行，避免阻塞事件循环
        dns_ok, dns_latency = await self.hass.async_add_executor_job(
            probe_dns, self.host, 53, 2.0
        )
        internet_ok, _ = await self.hass.async_add_executor_job(
            probe_tcp, "223.5.5.5", 53, 2.0
        )
        _, gateway_latency = await self.hass.async_add_executor_job(
            probe_tcp, self.host, 80, 2.0
        )
        data.dns_ok = dns_ok
        data.dns_latency = dns_latency
        data.internet_ok = internet_ok
        data.gateway_latency = gateway_latency

        try:
            proxies = await self.client.async_get_proxies()
        except Exception as err:  # noqa: BLE001 - API 不可达时仅降级
            _LOGGER.debug("mihomo API unavailable on %s: %s", self.host, err)
            return data

        data.proxies = proxies
        data.groups = {name: proxies[name] for name in SELECTABLE_GROUPS if name in proxies}
        data.current_node = (proxies.get(MAIN_GROUP) or {}).get("now")

        try:
            traffic = await self.client.async_get_traffic()
            data.up_rate = traffic["up"]
            data.down_rate = traffic["down"]
            data.up_total = traffic["up_total"]
            data.down_total = traffic["down_total"]
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("mihomo traffic unavailable: %s", err)

        try:
            conns = await self.client.async_get_connections()
            data.connections = len(conns.get("connections") or [])
            if not data.up_total:
                data.up_total = int(conns.get("uploadTotal") or 0)
                data.down_total = int(conns.get("downloadTotal") or 0)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("mihomo connections unavailable: %s", err)

        # /rules 体积较大，低频拉取；版本与模式变化也不频繁
        self._slow_tick += 1
        if self._slow_tick == 1 or self._slow_tick % 10 == 0:
            try:
                self._version = await self.client.async_get_version()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._mode = (await self.client.async_get_configs()).get("mode")
            except Exception:  # noqa: BLE001
                pass
            try:
                self._rules = await self.client.async_get_rule_count()
            except Exception:  # noqa: BLE001
                pass
        data.version = self._version
        data.mode = self._mode
        data.rules = self._rules
        return data
