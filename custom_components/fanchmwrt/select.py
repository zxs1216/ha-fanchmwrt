"""Select platform: OpenClash 分流组节点选择（v4 代理部分）。"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_OPENCLASH, DOMAIN
from .openclash import OpenClashCoordinator, openclash_selects


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the proxy-group selectors."""
    coordinator: OpenClashCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_OPENCLASH
    ]
    async_add_entities(openclash_selects(coordinator, entry))
