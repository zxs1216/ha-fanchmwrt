"""Regression tests for OpenClash subscription discovery and quota polling."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from multidict import CIMultiDict

from custom_components.fanchmwrt.openclash import subscription

HEADER = "upload=1073741824; download=2147483648; total=10737418240"


def test_parse_userinfo() -> None:
    parsed = subscription.parse_userinfo(
        "Download = 2147483648; TOTAL=10737418240; Upload=1073741824; expire="
    )
    assert parsed == subscription.Traffic(3, 10, 7, 30, None)
    assert subscription.parse_userinfo("upload=0; download=0; total=0") == (
        subscription.Traffic(0, None, None, None, None)
    )
    assert subscription.parse_userinfo("upload=1oops; download=2; total=3") is None


@pytest.mark.asyncio
async def test_openclash_source_precedence_and_multiple_plans() -> None:
    uci = """config openclash 'config'
    option config_path '/etc/openclash/config/active.yaml'
config config_subscribe
    option name 'active'
    option address 'https://example.test/download-only'
    option sub_ua 'custom-client'
    list sub_headers 'X-Example: configured'
config subscribe_info
    option name 'active'
    list url 'https://example.test/metadata#name=Primary'
    list url 'https://example.test/second#name=Secondary'
config config_subscribe
    option name 'yaml'
    option address 'https://example.test/ignored'
config config_subscribe
    option name 'other'
    option enabled '0'
    option address 'https://example.test/other
https://example.test/extra#name=Extra'
"""
    async def read(path: str) -> str | None:
        return (
            "proxy-providers:\n  Plan: {type: http, url: https://example.test/provider}"
            if path.endswith("/yaml.yaml") else None
        )

    router = MagicMock(read_file=AsyncMock(side_effect=read))
    catalog = await subscription._sources(router, uci)
    assert [(item.profile, item.name, item.active, item.url) for item in catalog] == [
        ("active", "Primary", True, "https://example.test/metadata"),
        ("active", "Secondary", True, "https://example.test/second"),
        ("yaml", "Plan", False, "https://example.test/provider"),
        ("other", "other", False, "https://example.test/other"),
        ("other", "Extra", False, "https://example.test/extra"),
    ]
    assert catalog[0].user_agent == "custom-client"
    assert catalog[0].headers == (("X-Example", "configured"),)
    rotated = await subscription._sources(router, uci.replace("/metadata", "/new-token"))
    assert catalog[0].key == rotated[0].key


@pytest.mark.asyncio
async def test_invalid_header_falls_back_and_other_plans_are_independent(monkeypatch) -> None:
    uci = """config openclash 'config'
    option config_path '/etc/openclash/config/first.yaml'
config config_subscribe
    option name 'first'
    option address 'https://example.test/first'
config config_subscribe
    option name 'second'
    option address 'https://example.test/second'
config config_subscribe
    option name 'third'
    option address 'https://example.test/third'
"""
    async def read(path: str) -> str | None:
        return uci if path == subscription.UCI_CONFIG_PATH else None

    async def request(method: str, url: str, **kwargs):
        headers = CIMultiDict()
        history = ()
        if url.endswith("/first"):
            headers.add("Subscription-UserInfo", "invalid" if method == "GET" else HEADER)
        elif url.endswith("/third"):
            history = (MagicMock(headers=CIMultiDict({"Subscription-UserInfo": HEADER})),)
        return MagicMock(status=200, headers=headers, history=history)

    session = MagicMock(request=AsyncMock(side_effect=request))
    monkeypatch.setattr(subscription, "async_get_clientsession", lambda hass: session)
    router = MagicMock(read_file=AsyncMock(side_effect=read))
    plans = await subscription.async_fetch_subscriptions(MagicMock(), router, {})
    assert plans is not None
    assert [(item.name, item.traffic is not None) for item in plans] == [
        ("first", True), ("second", False), ("third", True),
    ]
    assert not any(hasattr(item, "url") or hasattr(item, "headers") for item in plans)
