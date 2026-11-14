# mypy: disable-error-code="attr-defined,has-type,assignment"
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)

from ..const import (
    CONF_ASU_URL,
    CONF_ENABLE_FIREWALL,
    CONF_ENABLE_LOAD,
    CONF_ENABLE_SERVICES,
    CONF_ENABLE_VPN,
    CONF_AUTO_BACKUP,
    CONF_BACKUP_RETENTION_DAYS,
    CONF_CHECK_FIRMWARE_UPDATES,
    CONF_CONSIDER_HOME,
    CONF_CUSTOM_FIRMWARE_REPO,
    CONF_DHCP_SOFTWARE,
    CONF_FORCE_WIRELESS_MACS,
    CONF_GPS_MODEM_ENABLED,
    CONF_GPS_MODEM_PORT,
    CONF_GPS_POLL_INTERVAL,
    CONF_MANUAL_TRACKED_DEVICES,
    CONF_MQTT_PRESENCE,
    CONF_REDEPLOY_MQTT,
    CONF_REDEPLOY_USER,
    CONF_REVERSE_DNS,
    CONF_SKIP_RANDOM_MAC,
    CONF_TARGET_OVERRIDE,
    CONF_TRACK_WIRED,
    CONF_TRACKED_DEVICES,
    CONF_TRUST_BRIDGE_FDB,
    CONF_TRUST_STALE_ARP,
    CONF_UPDATE_INTERVAL,
    CONNECTION_TYPE_LUCI_RPC,
    CONNECTION_TYPE_SSH,
    CONNECTION_TYPE_UBUS,
    DATA_COORDINATOR,
    DEFAULT_BACKUP_RETENTION_DAYS,
    DEFAULT_CHECK_FIRMWARE_UPDATES,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_GPS_MODEM_ENABLED,
    DEFAULT_GPS_MODEM_PORT,
    DEFAULT_GPS_POLL_INTERVAL,
    DEFAULT_REVERSE_DNS,
    DEFAULT_SKIP_RANDOM_MAC,
    DEFAULT_TRACK_WIRED,
    DEFAULT_TRUST_BRIDGE_FDB,
    DEFAULT_TRUST_STALE_ARP,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .helpers import (
    _resolve_tracked_device_label,
    selector,
    should_redeploy_mqtt_presence,
    should_remove_mqtt_presence,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_MAP = {
    CONNECTION_TYPE_UBUS: "ubus (HTTP/HTTPS)",
    CONNECTION_TYPE_LUCI_RPC: "LuCI RPC",
    CONNECTION_TYPE_SSH: "SSH (not recommended)",
}

from .options_mqtt import OptionsMqttFlowMixin
from .options_packages import OptionsPackagesFlowMixin


class OpenWrtOptionsFlow(OptionsPackagesFlowMixin, OptionsMqttFlowMixin, OptionsFlow):
    """Handle options flow for OpenWrt."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry
        self._options: dict[str, Any] = {}
        self._permissions: Any = None
        self._packages: Any = None
        self._ubus_restricted: bool = False
        self._root_credentials: dict[str, Any] = {}

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the options: main settings only (旁路由精简)."""
        if user_input is not None:
            _LOGGER.debug("Options init submitted: %s", user_input)
            self._options = {**self._config_entry.options, **user_input}
            return self.async_create_entry(title="", data=self._options)

        current = self._config_entry.options
        # 旁路由精简：仅保留主要设置
        # （轮询间隔 / DHCP 来源 / 服务·防火墙·VPN·负载开关）
        schema_dict: dict[Any, Any] = {
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            vol.Optional(
                CONF_DHCP_SOFTWARE,
                default=current.get(CONF_DHCP_SOFTWARE, "auto"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["auto", "dnsmasq", "odhcpd", "none"],
                    translation_key="dhcp_software",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                ),
            ),
            vol.Optional(
                CONF_ENABLE_SERVICES,
                default=current.get(CONF_ENABLE_SERVICES, True),
            ): bool,
            vol.Optional(
                CONF_ENABLE_FIREWALL,
                default=current.get(CONF_ENABLE_FIREWALL, False),
            ): bool,
            vol.Optional(
                CONF_ENABLE_VPN,
                default=current.get(CONF_ENABLE_VPN, False),
            ): bool,
            vol.Optional(
                CONF_ENABLE_LOAD,
                default=current.get(CONF_ENABLE_LOAD, True),
            ): bool,
        }

        schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="init", data_schema=schema)

    async def _async_finalize_options(self) -> ConfigFlowResult:
        """Finalize options flow: deploy/remove MQTT if needed or create entry."""
        if should_remove_mqtt_presence(self._config_entry.options, self._options):
            return await self.async_step_options_do_remove_mqtt_presence()
        if should_redeploy_mqtt_presence(self._config_entry.options, self._options):
            return await self.async_step_options_do_deploy_mqtt_presence()
        return self.async_create_entry(title="", data=self._options)

    async def async_step_options_select_devices(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle selective device tracking step."""
        if user_input is not None:
            self._options.update(user_input)
            return await self._async_finalize_options()

        # Get discovered devices from coordinator
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
            DATA_COORDINATOR
        ]

        current = self._config_entry.options.get(CONF_TRACKED_DEVICES, [])
        current_manual = self._config_entry.options.get(CONF_MANUAL_TRACKED_DEVICES, "")

        # Candidates must come from the *unfiltered* device list. Only whitelisted
        # devices are ever written to _device_history, so sourcing candidates from
        # history alone makes them equal to the current selection — and a
        # multi-select only offers unselected options, so the dropdown renders
        # empty and the tracked set can never grow. all_connected_devices ignores
        # the whitelist (see the all_devices/filtered_devices split in the
        # coordinator) and carries real hostnames for readable labels.
        # Hostnames learned by any config entry. An access point runs no DHCP
        # server, so its own view of a client is MAC-only; without this its
        # picker would list bare MAC addresses.
        shared_hostnames: dict[str, str] = (
            self.hass.data.get(DOMAIN, {}).get("hostname_registry", {})
            if isinstance(getattr(self.hass, "data", None), dict)
            else {}
        )

        device_options: dict[str, str] = {}
        if coordinator.data:
            for device in coordinator.data.all_connected_devices:
                if not device.mac:
                    continue
                mac = device.mac.lower()
                device_options[mac] = _resolve_tracked_device_label(
                    mac=mac,
                    original_mac=device.mac,
                    hostname=device.hostname,
                    shared_hostnames=shared_hostnames,
                    hass=self.hass,
                )

            for lease in getattr(coordinator.data, "dhcp_leases", []):
                if not lease.mac:
                    continue
                mac = lease.mac.lower()
                if mac not in device_options:
                    device_options[mac] = _resolve_tracked_device_label(
                        mac=mac,
                        original_mac=lease.mac,
                        hostname=lease.hostname,
                        shared_hostnames=shared_hostnames,
                        hass=self.hass,
                        suffix=" [Lease]",
                    )

        # History keeps devices that were seen before but are offline right now
        # selectable.
        for mac, info in coordinator._device_history.items():
            if not isinstance(info, dict) or mac in device_options:
                continue
            hist_name = info.get("hostname") or info.get("name")
            device_options[mac] = _resolve_tracked_device_label(
                mac=mac.lower(),
                original_mac=mac,
                hostname=hist_name,
                shared_hostnames=shared_hostnames,
                hass=self.hass,
            )

        # An already tracked device that the coordinator has not seen yet must
        # stay in the list, otherwise the stored selection is not a valid option.
        for mac in current:
            if mac not in device_options:
                device_options[mac] = _resolve_tracked_device_label(
                    mac=mac.lower(),
                    original_mac=mac,
                    shared_hostnames=shared_hostnames,
                    hass=self.hass,
                )

        # Prepare device options for selector
        options: list[dict[str, str]] = sorted(
            [{"value": k, "label": v} for k, v in device_options.items()],
            key=lambda opt: opt["label"].lower(),
        )

        return self.async_show_form(
            step_id="options_select_devices",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TRACKED_DEVICES,
                        default=current,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_MANUAL_TRACKED_DEVICES,
                        default=current_manual,
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            multiline=True,
                            type=selector.TextSelectorType.TEXT,
                        )
                    ),
                }
            ),
        )
