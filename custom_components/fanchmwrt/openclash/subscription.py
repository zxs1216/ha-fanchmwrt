"""读取 OpenClash 各配置的订阅流量，不记录订阅地址或凭据。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shlex
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

import aiohttp
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

UCI_CONFIG_PATH = "/etc/config/openclash"
CONFIG_DIR = PurePosixPath("/etc/openclash/config")
HEADER_NAME = "subscription-userinfo"
GB = 1024**3
DEFAULT_UA = "Clash"
FALLBACK_UA = "Quantumultx"
REQUEST_TIMEOUT = 6


@dataclass(frozen=True)
class Traffic:
    """Subscription quota in GB, with an optional Unix expiration time."""

    used: float
    total: float | None
    remaining: float | None
    percent: float | None
    expires_at: int | None


@dataclass(frozen=True)
class Subscription:
    """Public subscription identity and polling result."""

    key: str
    profile: str
    name: str
    active: bool
    traffic: Traffic | None


@dataclass(frozen=True, repr=False)
class _Source:
    key: str
    profile: str
    name: str
    active: bool
    url: str
    user_agent: str
    headers: tuple[tuple[str, str], ...]


def _uci_sections(text: str) -> list[tuple[str, dict[str, str], dict[str, list[str]]]]:
    """Read option and list values, including quoted values spanning lines."""
    sections: list[tuple[str, dict[str, str], dict[str, list[str]]]] = []
    pending = ""
    for line in text.splitlines(keepends=True):
        pending += line
        try:
            tokens = shlex.split(pending, comments=True)
        except ValueError:
            continue
        pending = ""
        if len(tokens) >= 2 and tokens[0] == "config":
            sections.append((tokens[1], {}, {}))
        elif len(tokens) == 3 and sections:
            kind, key, value = tokens
            _, options, lists = sections[-1]
            if kind == "option":
                options[key] = value
            elif kind == "list":
                lists.setdefault(key, []).append(value)
    return sections


def _url_entries(values: Iterable[str]) -> Iterator[tuple[str, str]]:
    for value in values:
        for line in value.splitlines():
            url, _, name = line.strip().partition("#")
            try:
                parts = urlsplit(url)
                if parts.scheme in ("http", "https") and parts.hostname:
                    yield url, unquote(name[5:]).strip() if name.startswith("name=") else ""
            except ValueError:
                continue


def _request_headers(values: Iterable[str]) -> Iterator[tuple[str, str]]:
    for value in values:
        for line in value.splitlines():
            name, colon, val = line.partition(":")
            name = name.strip()
            if colon and re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", name):
                if name.lower() != "user-agent":
                    yield name, val.strip()


async def _yaml_sources(router_client: Any, path: PurePosixPath) -> list[tuple[str, str]]:
    """Read HTTP providers from a local OpenClash profile, when accessible."""
    try:
        if not (text := await router_client.read_file(str(path))):
            return []
        # Large generated profiles must not block Home Assistant's event loop.
        doc = await asyncio.to_thread(yaml.safe_load, text)
    except Exception:  # noqa: BLE001 - optional source; addresses may contain credentials
        return []
    providers = doc.get("proxy-providers") if isinstance(doc, dict) else None
    if not isinstance(providers, dict):
        return []
    return [
        (url, str(name))
        for name, config in providers.items()
        if isinstance(config, dict) and isinstance(config.get("url"), str)
        for url, _ in _url_entries([config["url"]])
    ]


async def _sources(router_client: Any, uci: str) -> list[_Source]:
    active_path = PurePosixPath()
    profiles: dict[str, tuple[dict[str, str], dict[str, list[str]]]] = {}
    overrides: dict[str, list[tuple[str, str]]] = {}
    for kind, options, lists in _uci_sections(uci):
        if kind == "openclash" and options.get("config_path"):
            active_path = PurePosixPath(options["config_path"])
        name = options.get("name", "")
        if not name or PurePosixPath(name).name != name or name in (".", ".."):
            continue
        if kind == "config_subscribe":
            profiles[name] = (options, lists)
        elif kind == "subscribe_info":
            values = _url_entries([options.get("url", ""), *lists.get("url", [])])
            overrides.setdefault(name, []).extend(values)

    active = active_path.stem if active_path.suffix.lower() in (".yaml", ".yml") else ""
    names = dict.fromkeys(filter(None, (active, *profiles, *overrides)))
    catalog = []
    for profile in names:
        options, lists = profiles.get(profile, ({}, {}))
        entries = overrides.get(profile) or await _yaml_sources(
            router_client, CONFIG_DIR / (active_path.name if profile == active else f"{profile}.yaml")
        )
        if not entries:
            entries = list(_url_entries([options.get("address", ""), *lists.get("address", [])]))
        seen_urls: set[str] = set()
        seen_names: dict[str, int] = {}
        for url, label in entries:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            label = label or profile
            ordinal = seen_names[label] = seen_names.get(label, 0) + 1
            key = hashlib.sha256(f"{profile}\0{label}\0{ordinal}".encode()).hexdigest()[:16]
            catalog.append(
                _Source(
                    key, profile, label if ordinal == 1 else f"{label} ({ordinal})",
                    profile == active, url, options.get("sub_ua") or DEFAULT_UA,
                    tuple(_request_headers([options.get("sub_headers", ""), *lists.get("sub_headers", [])])),
                )
            )
    return catalog


def parse_userinfo(header: str) -> Traffic | None:
    """Parse complete counters; OpenClash treats total=0 as unlimited."""
    values: dict[str, int] = {}
    for field in re.split(r"[;,]", header):
        key, _, value = field.partition("=")
        key, value = key.strip().lower(), value.strip()
        if key in ("upload", "download", "total", "expire") and re.fullmatch(r"[0-9]{1,20}", value):
            values[key] = int(value)
    if not {"upload", "download", "total"} <= values.keys():
        return None
    used = values["upload"] + values["download"]
    total = values["total"]
    expire = values.get("expire", 0)
    return Traffic(
        used=round(used / GB, 2),
        total=round(total / GB, 2) if total else None,
        remaining=round(max(total - used, 0) / GB, 2) if total else None,
        percent=round(used / total * 100, 1) if total else None,
        expires_at=expire if 0 < expire <= 253402300799 else None,
    )


def _first_valid(headers: Iterable[str]) -> Traffic | None:
    return next((info for header in headers if (info := parse_userinfo(header))), None)


async def _direct_fetch(
    session: aiohttp.ClientSession, source: _Source, method: str, user_agent: str
) -> Traffic | None:
    try:
        response = await session.request(
            method, source.url,
            headers=[("User-Agent", user_agent), *source.headers],
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            allow_redirects=not source.headers,
        )
        try:
            if 200 <= response.status < 300:
                for item in (response, *reversed(response.history)):
                    if traffic := _first_valid(item.headers.getall(HEADER_NAME, [])):
                        return traffic
        finally:
            response.close()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        pass
    return None


def _ssh_fetch(ssh: dict[str, Any], source: _Source) -> Traffic | None:
    """Use the router's curl with the same header-only GET as OpenClash."""
    import paramiko  # noqa: PLC0415 - HA installs the manifest dependency

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            ssh["host"], int(ssh.get("port", 22)),
            username=ssh.get("username") or "root", password=ssh["password"],
            timeout=REQUEST_TIMEOUT, banner_timeout=REQUEST_TIMEOUT,
            auth_timeout=REQUEST_TIMEOUT, allow_agent=False, look_for_keys=False,
        )
        for user_agent in dict.fromkeys((source.user_agent, DEFAULT_UA, FALLBACK_UA)):
            args = [
                "curl", "-q", "--silent", "--head", "--request", "GET",
                "--globoff", "--max-time", str(REQUEST_TIMEOUT),
                "--proto", "=http,https", "--proto-redir", "=http,https",
                "--write-out", "\n%{http_code}", "--user-agent", user_agent,
            ]
            if not source.headers:
                args += ["--location", "--max-redirs", "5"]
            for name, value in source.headers:
                args += ["--header", f"{name}: {value}"]
            args += ["--", source.url]
            _, stdout, _ = client.exec_command(shlex.join(args), timeout=REQUEST_TIMEOUT + 2)
            *lines, status = stdout.read().decode("utf-8", "replace").splitlines() or [""]
            if re.fullmatch(r"2[0-9]{2}", status):
                headers = (
                    value for line in reversed(lines)
                    for name, colon, value in [line.partition(":")]
                    if colon and name.lower() == HEADER_NAME
                )
                if traffic := _first_valid(headers):
                    return traffic
    finally:
        client.close()
    return None


async def async_fetch_subscriptions(
    hass: HomeAssistant, router_client: Any, ssh: dict[str, Any]
) -> tuple[Subscription, ...] | None:
    """Poll the complete catalog; a failed source does not affect other plans."""
    try:
        uci = await router_client.read_file(UCI_CONFIG_PATH)
        if not uci:
            return None
        catalog = await _sources(router_client, uci)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("无法读取 OpenClash 订阅配置 (%s)", type(err).__name__)
        return None

    session = async_get_clientsession(hass)
    slots = asyncio.Semaphore(4)

    async def fetch(source: _Source) -> Subscription:
        async with slots:
            traffic = await _direct_fetch(session, source, "GET", source.user_agent)
            if traffic is None:
                traffic = await _direct_fetch(session, source, "HEAD", source.user_agent)
            if traffic is None and ssh.get("host") and ssh.get("password"):
                try:
                    traffic = await hass.async_add_executor_job(_ssh_fetch, ssh, source)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("路由器订阅查询失败 (%s)", type(err).__name__)
            if traffic is None:
                for user_agent in dict.fromkeys((DEFAULT_UA, FALLBACK_UA)):
                    if user_agent != source.user_agent:
                        traffic = await _direct_fetch(session, source, "GET", user_agent)
                        if traffic is not None:
                            break
            return Subscription(source.key, source.profile, source.name, source.active, traffic)

    return tuple(await asyncio.gather(*(fetch(source) for source in catalog)))
