"""DataUpdateCoordinator for the Dimplex System M (UHI) integration."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UhiApiClient, UhiApiError
from .const import CONF_LANGUAGE, DEFAULT_LANGUAGE, DOMAIN, SNAPSHOT_GROUPS

_LOGGER = logging.getLogger(__name__)


class DimplexUhiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages snapshot polling, live updates and master data of a UHI."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: UhiApiClient,
        state_interval: float,
        version_interval: float,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=state_interval),
        )
        self.entry = entry
        self.client = client
        self._version_interval = version_interval
        self._last_version_poll: float = 0.0

        # Master data / metadata
        self.definitions: dict[str, dict] = {}
        self.key_group: dict[str, str] = {}
        self.version: dict[str, Any] = {}
        self.mac: str | None = None
        self.mode_id_to_name: dict[int, str] = {}
        self.mode_name_to_id: dict[str, int] = {}
        self.mode_names: list[str] = []
        self.current_mode_id: int | None = None

        # Platform callbacks to discover new keys dynamically.
        self._known_keys: set[str] = set()
        self.new_key_listeners: list[Any] = []

    # ---------------- Setup ----------------
    async def async_prepare(self) -> None:
        """One-time initialization of version and operation-mode list."""
        await self._async_refresh_version()
        await self._async_refresh_modes()
        await self._async_refresh_current_mode()
        self.client.set_operationdata_handler(self._handle_live_values)

    async def async_connect_socket(self, socket_url: str | None = None) -> None:
        try:
            await self.client.connect_socket(socket_url)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Socket.IO connection failed: %s", exc)

    # ---------------- Polling ----------------
    async def _async_update_data(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._last_version_poll >= self._version_interval:
            await self._async_refresh_version()
        await self._async_refresh_current_mode()

        try:
            groups = await self.client.get_function_data_groups(SNAPSHOT_GROUPS)
        except UhiApiError as exc:
            raise UpdateFailed(str(exc)) from exc

        values: dict[str, Any] = dict(self.data or {})
        for group_name, items in groups.items():
            if not isinstance(items, list):
                continue
            for item in items:
                key = item.get("key")
                if key is None:
                    continue
                values[key] = item.get("value")
                self.key_group[key] = group_name
                definition = item.get("definition")
                if isinstance(definition, dict):
                    self.definitions[key] = definition
        self._notify_new_keys(values.keys())
        return values

    async def _async_refresh_version(self) -> None:
        try:
            version = await self.client.get_version()
        except UhiApiError as exc:
            _LOGGER.debug("Version not readable: %s", exc)
            return
        self._last_version_poll = time.monotonic()
        self.version = version
        uhi = version.get("uhi") or {}
        if uhi.get("mac"):
            self.mac = uhi["mac"]

    async def _async_refresh_modes(self) -> None:
        try:
            modes = await self.client.get_operation_mode_list()
        except UhiApiError as exc:
            _LOGGER.debug("Operation mode list not readable: %s", exc)
            return
        self.mode_id_to_name = {}
        self.mode_name_to_id = {}
        self.mode_names = []
        for item in modes:
            try:
                mode_id = int(item["id"])
            except (KeyError, ValueError, TypeError):
                continue
            name = item.get("name")
            if not name:
                continue
            self.mode_id_to_name[mode_id] = name
            self.mode_name_to_id[name] = mode_id
            self.mode_names.append(name)

    async def _async_refresh_current_mode(self) -> None:
        try:
            data = await self.client.get_operation_mode()
        except UhiApiError as exc:
            _LOGGER.debug("Current operation mode not readable: %s", exc)
            return
        mode = data.get("operationMode") if isinstance(data, dict) else None
        if isinstance(mode, dict) and mode.get("id") is not None:
            try:
                self.current_mode_id = int(mode["id"])
            except (ValueError, TypeError):
                self.current_mode_id = None

    # ---------------- Live (Socket.IO) ----------------
    async def _handle_live_values(self, values: dict[str, Any]) -> None:
        merged: dict[str, Any] = dict(self.data or {})
        merged.update(values)
        self._notify_new_keys(merged.keys())
        self.async_set_updated_data(merged)

    # ---------------- Dynamic keys ----------------
    @callback
    def _notify_new_keys(self, keys) -> None:
        new = [k for k in keys if k not in self._known_keys]
        if not new:
            return
        self._known_keys.update(new)
        for listener in list(self.new_key_listeners):
            listener(new)

    @callback
    def add_new_key_listener(self, listener) -> None:
        self.new_key_listeners.append(listener)

    @callback
    def apply_local_value(self, key: str, value: Any) -> None:
        """Apply a locally written value into the data immediately.

        Needed for writable keys that are not actively polled: without this,
        an older value (delivered via the socket) would take precedence and the
        input would appear to jump back.
        """
        data = dict(self.data or {})
        data[key] = value
        self.async_set_updated_data(data)

    @property
    def identifier(self) -> str:
        """Stable identifier (MAC if known, otherwise the config entry id)."""
        return self.mac or self.entry.entry_id

    @property
    def language(self) -> str:
        """Selected UI language (options override data, default 'de')."""
        return self.entry.options.get(
            CONF_LANGUAGE, self.entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        )

    @property
    def known_keys(self) -> set[str]:
        return set(self._known_keys)

    # ---------------- Writing ----------------
    async def async_set_function_data(self, key: str, value: Any) -> None:
        await self.client.set_function_data(key, value)

    async def async_set_operation_mode(self, mode_id: int) -> None:
        await self.client.set_operation_mode(mode_id)
        self.current_mode_id = mode_id
        self.async_update_listeners()
