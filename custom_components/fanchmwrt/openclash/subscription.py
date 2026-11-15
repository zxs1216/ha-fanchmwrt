"""OpenClash 订阅剩余流量。

OpenClash 的 LuCI 页面通过实时请求订阅地址、读取响应头
``subscription-userinfo: upload=...; download=...; total=...; expire=...``
来显示「剩余流量」。服务端不落盘该数值，因此这里复刻同一路径：

1. 通过 ubus ``file.read`` 读 ``/etc/config/openclash``，找到当前启用配置
   对应的订阅地址（``config_subscribe`` 段）；
2. 低频 GET 该地址，只取响应头并立即关闭连接，不下载订阅内容；
3. 解析并换算为 GB，供 HA 传感器使用。
"""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

UCI_CONFIG_PATH = "/etc/config/openclash"
GB = 1024**3
SUBSCRIBER_UA = "clash-verge/v2.4.5"


def parse_subscription_url(uci_text: str) -> str | None:
    """从 UCI 配置里定位当前配置文件对应的订阅地址。"""
    config_name = ""
    path_match = re.search(r"option\s+config_path\s+'([^']+)'", uci_text)
    if path_match:
        base = path_match.group(1).rsplit("/", 1)[-1]
        config_name = re.sub(r"\.ya?ml$", "", base)

    first_enabled: str | None = None
    for block in re.split(r"(?m)^config\s+", uci_text):
        if not block.lstrip().startswith("config_subscribe"):
            continue
        address = re.search(r"option\s+address\s+'([^']+)'", block)
        if not address:
            continue
        enabled = re.search(r"option\s+enabled\s+'([^']+)'", block)
        name = re.search(r"option\s+name\s+'([^']+)'", block)
        is_enabled = not enabled or enabled.group(1) == "1"
        if is_enabled and first_enabled is None:
            first_enabled = address.group(1)
        if config_name and name and name.group(1) == config_name:
            return address.group(1)
    return first_enabled


def parse_userinfo(header: str) -> dict[str, float] | None:
    """解析 subscription-userinfo 响应头，产出 GB / 百分比。"""
    up = re.search(r"upload=(\d+)", header)
    down = re.search(r"download=(\d+)", header)
    total = re.search(r"total=(\d+)", header)
    if not (up and down and total):
        return None
    upload, download, limit = int(up.group(1)), int(down.group(1)), int(total.group(1))
    if limit <= 0:
        return None
    used = upload + download
    return {
        "total": round(limit / GB, 2),
        "used": round(used / GB, 2),
        "remaining": round(max(limit - used, 0) / GB, 2),
        "percent": round(used / limit * 100, 1),
    }


async def async_fetch_subscription(
    hass: HomeAssistant, router_client: Any
) -> dict[str, float] | None:
    """低频获取一次订阅流量信息，任何失败都返回 None（不阻断集成）。"""
    try:
        uci_text = await router_client.read_file(UCI_CONFIG_PATH)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("读取 OpenClash UCI 配置失败: %s", err)
        return None
    if not uci_text:
        return None

    url = parse_subscription_url(uci_text)
    if not url:
        return None

    response = None
    try:
        session = async_get_clientsession(hass)
        response = await session.get(
            url,
            headers={"User-Agent": SUBSCRIBER_UA},
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=False,
            allow_redirects=True,
        )
        header = response.headers.get("subscription-userinfo", "")
        return parse_userinfo(header)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("获取订阅流量信息失败: %s", err)
        return None
    finally:
        if response is not None:
            response.close()
