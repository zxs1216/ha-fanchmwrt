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
import shlex
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
    if not header or not header.strip():
        return None

    # 记录接收到的响应头用于调试
    _LOGGER.debug("订阅响应头内容: %s", header[:200])

    up = re.search(r"upload=(\d+)", header)
    down = re.search(r"download=(\d+)", header)
    total = re.search(r"total=(\d+)", header)

    if not (up and down and total):
        _LOGGER.debug(
            "订阅响应头解析失败 - upload: %s, download: %s, total: %s",
            bool(up), bool(down), bool(total)
        )
        return None

    upload, download, limit = int(up.group(1)), int(down.group(1)), int(total.group(1))
    if limit <= 0:
        _LOGGER.debug("订阅流量总额无效: %d", limit)
        return None

    used = upload + download
    return {
        "total": round(limit / GB, 2),
        "used": round(used / GB, 2),
        "remaining": round(max(limit - used, 0) / GB, 2),
        "percent": round(used / limit * 100, 1),
    }


def _ssh_fetch_header(
    host: str, username: str, password: str, url: str
) -> str:
    """兜底：在路由器上执行 curl 取订阅响应头（该路径已实测可用）。"""
    import paramiko  # noqa: PLC0415 - HA 已通过 manifest 安装

    command = (
        "curl -sk -D - -o /dev/null --max-time 20 "
        f"-A '{SUBSCRIBER_UA}' {shlex.quote(url)} "
        "| grep -i '^subscription-userinfo:'"
    )
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            host,
            22,
            username=username or "root",
            password=password,
            timeout=8,
            allow_agent=False,
            look_for_keys=False,
        )
        _, stdout, _ = client.exec_command(command, timeout=30)
        return stdout.read().decode("utf-8", "ignore").strip()
    finally:
        client.close()


async def async_fetch_subscription(
    hass: HomeAssistant,
    router_client: Any,
    ssh: dict[str, str] | None = None,
) -> dict[str, float] | None:
    """低频获取一次订阅流量信息，任何失败都返回 None（不阻断集成）。

    优先由 HA 主机直接请求订阅地址；若主机网络受限，则回退到在路由器上
    执行 curl（与 OpenClash LuCI 页面相同的数据来源）。
    """
    try:
        uci_text = await router_client.read_file(UCI_CONFIG_PATH)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("读取 OpenClash UCI 配置失败: %s", err)
        return None
    if not uci_text:
        _LOGGER.warning("OpenClash UCI 配置为空，无法定位订阅地址")
        return None

    url = parse_subscription_url(uci_text)
    if not url:
        _LOGGER.warning("未能从 UCI 配置解析出订阅地址")
        return None

    _LOGGER.debug("准备请求订阅地址: %s", url[:50] + "...")

    header = ""
    response = None
    try:
        session = async_get_clientsession(hass)
        response = await session.get(
            url,
            headers={"User-Agent": SUBSCRIBER_UA},
            timeout=aiohttp.ClientTimeout(total=12),
            ssl=False,
            allow_redirects=True,
        )
        header = response.headers.get("subscription-userinfo", "")
        if header:
            _LOGGER.debug("成功获取订阅响应头")
        else:
            _LOGGER.debug("订阅响应头中未包含 subscription-userinfo 字段")
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("HA 直连订阅地址失败，尝试路由器兜底: %s", err)
    finally:
        if response is not None:
            response.close()

    if not header and ssh and ssh.get("host") and ssh.get("password"):
        try:
            _LOGGER.debug("通过 SSH 在路由器上执行 curl 获取订阅信息")
            header = await hass.async_add_executor_job(
                _ssh_fetch_header,
                ssh["host"],
                ssh.get("username", "root"),
                ssh["password"],
                url,
            )
            if header:
                _LOGGER.debug("SSH 兜底成功获取订阅响应头")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("路由器兜底获取订阅信息失败: %s", err)

    parsed = parse_userinfo(header)
    if parsed is None and header:
        # 只在有响应头但解析失败时才记录警告
        _LOGGER.warning(
            "订阅响应头存在但解析失败，请检查响应头格式。响应头内容: %s",
            header[:200] if header else "(空)"
        )
    elif parsed is None:
        # 完全没有响应头，降级为 debug
        _LOGGER.debug(
            "未获取到订阅响应头 subscription-userinfo，可能订阅服务商未提供流量信息"
        )
    return parsed
