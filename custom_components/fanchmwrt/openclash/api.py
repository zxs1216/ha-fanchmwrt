"""mihomo (OpenClash) REST client plus lightweight network probes.

只依赖 HA 自带的 aiohttp 会话与 Python 标准库，不引入新的 pip 依赖。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import socket
import struct
import time
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


def probe_tcp(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float | None]:
    """TCP 连通性探测，返回 (是否可达, 毫秒)。同步函数，需在 executor 中调用。"""
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, round((time.monotonic() - started) * 1000, 1)
    except OSError:
        return False, None


def probe_dns(
    host: str, port: int = 53, timeout: float = 2.0
) -> tuple[bool, float | None]:
    """向指定 DNS 服务器发一个 A 查询，返回 (是否成功, 毫秒)。"""
    query_id = random.randint(0, 65535)
    packet = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
    for label in "www.baidu.com".split("."):
        packet += bytes([len(label)]) + label.encode("ascii")
    packet += b"\x00" + struct.pack("!HH", 1, 1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    started = time.monotonic()
    try:
        sock.sendto(packet, (host, port))
        data, _ = sock.recvfrom(512)
        latency = round((time.monotonic() - started) * 1000, 1)
        # rcode 位于第 4 字节低 4 位，0 = NoError
        ok = len(data) > 12 and (data[3] & 0x0F) == 0
        return ok, latency
    except OSError:
        return False, None
    finally:
        sock.close()


class MihomoClient:
    """精简的 mihomo External Controller 客户端。"""

    def __init__(
        self, hass: HomeAssistant, host: str, port: int = 9090, secret: str = ""
    ) -> None:
        self.host = host
        self.port = port
        self._session = async_get_clientsession(hass)
        self._base = f"http://{host}:{port}"
        self._headers = {"Authorization": f"Bearer {secret}"} if secret else {}

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        async with self._session.request(
            method,
            self._base + path,
            headers=self._headers,
            timeout=aiohttp.ClientTimeout(total=6),
            **kwargs,
        ) as resp:
            resp.raise_for_status()
            if resp.status == 204:
                return {}
            text = await resp.text()
            return json.loads(text) if text else {}

    async def async_get_version(self) -> str | None:
        data = await self._request("GET", "/version")
        return str(data.get("version") or "unknown")

    async def async_get_proxies(self) -> dict[str, dict[str, Any]]:
        data = await self._request("GET", "/proxies")
        return data.get("proxies") or {}

    async def async_get_configs(self) -> dict[str, Any]:
        return await self._request("GET", "/configs")

    async def async_get_connections(self) -> dict[str, Any]:
        return await self._request("GET", "/connections")

    async def async_get_rule_count(self) -> int:
        data = await self._request("GET", "/rules")
        return len(data.get("rules") or [])

    async def async_get_traffic(self) -> dict[str, int]:
        """/traffic 是 SSE 流，只读第一行，避免长连接卡住整个轮询。"""
        url = self._base + "/traffic"
        try:
            async with self._session.get(
                url,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=4, sock_read=2),
            ) as resp:
                resp.raise_for_status()
                line = await asyncio.wait_for(resp.content.readline(), 3)
                data = json.loads(line)
                return {
                    "up": int(data.get("up") or 0),
                    "down": int(data.get("down") or 0),
                    "up_total": int(data.get("upTotal") or 0),
                    "down_total": int(data.get("downTotal") or 0),
                }
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.debug("mihomo /traffic unavailable: %s", err)
            return {"up": 0, "down": 0, "up_total": 0, "down_total": 0}

    async def async_select_node(self, group: str, node: str) -> None:
        """切换分流组当前节点。"""
        await self._request(
            "PUT", f"/proxies/{quote(group, safe='')}", json={"name": node}
        )

    async def async_flush_dns_cache(self) -> None:
        """清空 Fake-IP / DNS 缓存。"""
        await self._request("POST", "/cache/fakeip/flush")
