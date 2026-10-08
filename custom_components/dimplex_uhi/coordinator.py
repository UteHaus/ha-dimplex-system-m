"""DataUpdateCoordinator for the Dimplex System M (UHI) integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import UhiApiClient, UhiApiError, UhiAuthError, path_parts
from .const import (
    CONF_LANGUAGE,
    CONF_PARTY_HOURS,
    CONNECTED_POLL_INTERVAL,
    DEFAULT_LANGUAGE,
    DEFAULT_PARTY_HOURS,
    DOMAIN,
    SKIPPED_GROUP_RETRY,
    SNAPSHOT_GROUPS,
    SOCKET_SILENT_AFTER,
)

# Live key carrying the active operation mode (same id as /api/operationmode).
MODE_KEY = "BA_aktiv"
# Timed modes: the UHI rejects them without an end date.
MODE_HOLIDAY = 2
MODE_PARTY = 3
# Automatic mode switching limits of the operationmode API.
MODE_LIMIT_FIELDS = ("limitTempHeating", "limitTempCooling", "delayTimeHours")
HOT_WATER_UNIT = "WW"
POOL_TYPE = "SCHWIMMBAD"
WW_MIN_KEY = "P_WW_MIN_TEMP"

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
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=state_interval),
        )
        self.entry = entry
        self.client = client
        self._version_interval = version_interval
        self._last_version_poll: float = 0.0
        self._last_snapshot: float = 0.0
        self._socket_seen = False
        self._last_bundle: float = 0.0
        # group -> monotonic time it was skipped
        self._skipped_groups: dict[str, float] = {}
        self._socket_task: asyncio.Task | None = None
        self._socket_warned = False

        # Master data / metadata
        self.definitions: dict[str, dict] = {}
        self.key_group: dict[str, str] = {}
        self.version: dict[str, Any] = {}
        self.mac: str | None = None
        self.mode_id_to_name: dict[int, str] = {}
        self.mode_name_to_id: dict[str, int] = {}
        self.mode_names: list[str] = []
        self.current_mode_id: int | None = None
        self.is_automatic: bool | None = None
        self.mode_limits: dict[str, float] = {}
        # Heating units (circuits, rooms, hot water, pool) by id; each:
        # { id, type, name, min, max, step, target, current, rapidheating }
        self.heating_units: dict[str, dict[str, Any]] = {}

        # Platform callbacks to discover new keys dynamically.
        self._known_keys: set[str] = set()
        self.new_key_listeners: list[Any] = []

    # ---------------- Setup ----------------
    async def async_prepare(self) -> None:
        """One-time initialization of version and operation-mode list."""
        await self._async_refresh_version()
        await self._async_refresh_modes()
        await self._async_refresh_current_mode()
        await self._async_refresh_heating_units()
        self.client.set_operationdata_handler(self._handle_live_values)
        self.client.set_connect_handler(self._handle_socket_connect)
        self.client.set_api_response_handler(self._handle_api_response)

    async def async_connect_socket(self) -> None:
        try:
            await self.client.connect_socket()
        except Exception as exc:  # noqa: BLE001
            # Only warn once; retries happen on every poll until it works.
            log = _LOGGER.debug if self._socket_warned else _LOGGER.warning
            log("Socket.IO connection failed (retrying on next poll): %s", exc)
            self._socket_warned = True
        else:
            self._socket_warned = False

    @callback
    def _ensure_socket(self) -> None:
        """(Re)start the socket connection in the background if needed."""
        if self.client.socket_active:
            return
        if self._socket_task is not None and not self._socket_task.done():
            return
        self._socket_task = self.entry.async_create_background_task(
            self.hass, self.async_connect_socket(), f"{DOMAIN} socket connect"
        )

    @callback
    def _handle_socket_connect(self) -> None:
        """Catch up on changes missed while the socket was down."""
        # Grace period until the first change bundle arrives.
        self._last_bundle = time.monotonic()
        if not self._socket_seen:
            # First connect right after setup: the snapshot is fresh.
            self._socket_seen = True
            return
        self._last_snapshot = 0.0
        self.entry.async_create_background_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN} refresh on connect"
        )

    # ---------------- Polling ----------------
    async def _async_update_data(self) -> dict[str, Any]:
        self._ensure_socket()
        now = time.monotonic()
        if now - self._last_version_poll >= self._version_interval:
            await self._async_refresh_version()
        if not self.mode_names:
            await self._async_refresh_modes()
        # With a connected socket values, groups and mode arrive as push
        # (change bundles and re-broadcast API responses), so the snapshot is
        # only a safety net. Every request runs a script on the UHI.
        if self.socket_alive and now - self._last_snapshot < CONNECTED_POLL_INTERVAL:
            return dict(self.data or {})
        await self._async_refresh_current_mode()
        await self._async_refresh_heating_units()

        try:
            groups = await self._async_fetch_groups()
        except UhiApiError as exc:
            raise UpdateFailed(str(exc)) from exc
        self._last_snapshot = time.monotonic()

        values: dict[str, Any] = dict(self.data or {})
        for group_name, items in groups.items():
            self._merge_items(values, items, group_name)
        self._notify_new_keys(values.keys())
        return values

    @property
    def socket_alive(self) -> bool:
        """Connected and actually delivering change bundles."""
        return (
            self.client.socket_connected
            and time.monotonic() - self._last_bundle < SOCKET_SILENT_AFTER
        )

    async def _async_fetch_groups(self) -> dict[str, Any]:
        """Read all snapshot groups, tolerating groups the UHI rejects.

        The UHI fails the whole request if a single group is unknown or one
        of its variables is unreadable (e.g. after a UHI update). Then fall
        back to one request per group and skip the failing ones for a while.
        """
        now = time.monotonic()
        wanted = [
            group
            for group in SNAPSHOT_GROUPS
            if now - self._skipped_groups.get(group, -SKIPPED_GROUP_RETRY)
            >= SKIPPED_GROUP_RETRY
        ]
        try:
            return await self.client.get_function_data_groups(wanted)
        except UhiAuthError:
            raise
        except UhiApiError as exc:
            if len(wanted) == 1:
                raise
            _LOGGER.debug("Group request failed, reading groups one by one: %s", exc)

        groups: dict[str, Any] = {}
        failed: dict[str, UhiApiError] = {}
        for group in wanted:
            try:
                groups.update(await self.client.get_function_data_groups([group]))
            except UhiAuthError:
                raise
            except UhiApiError as exc:
                failed[group] = exc
        if not groups:
            # Nothing readable: a connection problem, not a changed UHI.
            raise next(iter(failed.values()))
        for group, exc in failed.items():
            if group not in self._skipped_groups:
                _LOGGER.warning(
                    "UHI group %s is not readable and is skipped (retry in %d s): %s",
                    group,
                    SKIPPED_GROUP_RETRY,
                    exc,
                )
            self._skipped_groups[group] = now
        for group in groups:
            self._skipped_groups.pop(group, None)
        return groups

    def _merge_items(
        self, values: dict[str, Any], items: Any, group_name: str | None
    ) -> None:
        """Merge [{ key, value, definition }, ...] into values/metadata."""
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict) or item.get("key") is None:
                continue
            key = item["key"]
            values[key] = item.get("value")
            if group_name is not None:
                self.key_group[key] = group_name
            definition = item.get("definition")
            if isinstance(definition, dict):
                self.definitions[key] = definition

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
        self._apply_mode_response(data)

    @callback
    def _apply_mode_response(self, data: dict[str, Any]) -> None:
        """Take over { id, is_automatic_mode, ... } from GET/PUT operationmode."""
        try:
            self.current_mode_id = int(data["id"])
        except (KeyError, ValueError, TypeError):
            pass
        auto = data.get("is_automatic_mode")
        if auto is not None:
            try:
                self.is_automatic = bool(int(auto))
            except (ValueError, TypeError):
                pass
        for field in MODE_LIMIT_FIELDS:
            if isinstance(data.get(field), (int, float)):
                self.mode_limits[field] = data[field]

    async def _async_refresh_heating_units(self) -> None:
        """Read the heating units the UHI offers for adjustment."""
        try:
            configs = await self.client.get_heating_units()
        except UhiApiError as exc:
            _LOGGER.debug("Heating units not readable: %s", exc)
            return
        for config in configs:
            if not isinstance(config, dict) or not config.get("id"):
                continue
            unit_id = str(config["id"])
            if not config.get("variableValues"):
                # The pool is listed without values; fetch them separately.
                try:
                    config[
                        "variableValues"
                    ] = await self.client.get_heating_unit_temperature(unit_id)
                except UhiApiError:
                    config["variableValues"] = {}
            self._apply_heating_unit_config(config)

    @callback
    def _apply_heating_unit_config(self, config: dict[str, Any]) -> None:
        unit_id = str(config["id"])
        limits = config.get("targetTemperature") or {}
        caps = config.get("capabilities") or {}
        values = config.get("variableValues") or {}
        unit = self.heating_units.setdefault(unit_id, {"id": unit_id})
        unit.update(
            type=config.get("type"),
            name=config.get("name") or unit_id,
            min=limits.get("min"),
            max=limits.get("max"),
            step=caps.get("set_temperature_delta") or 1,
            settable=bool(config.get("setTemperature")),
        )
        self._apply_heating_unit_values(unit_id, values)

    @callback
    def _apply_heating_unit_values(self, unit_id: str, values: Any) -> None:
        """Take over { current, target, rapidheating: { level } }."""
        unit = self.heating_units.get(unit_id)
        if unit is None or not isinstance(values, dict):
            return
        for field in ("current", "target"):
            if isinstance(values.get(field), (int, float)):
                unit[field] = values[field]
        rapid = values.get("rapidheating")
        if isinstance(rapid, dict) and rapid.get("level") is not None:
            unit["rapidheating"] = int(rapid["level"])

    def heating_unit_present(self, unit_id: str) -> bool:
        """The pool is listed when configured; only use it with a reading."""
        unit = self.heating_units.get(unit_id) or {}
        if unit.get("type") == POOL_TYPE:
            return bool(unit.get("current"))
        return True

    # ---------------- Live (Socket.IO) ----------------
    async def _handle_live_values(self, values: dict[str, Any]) -> None:
        self._last_bundle = time.monotonic()
        merged: dict[str, Any] = dict(self.data or {})
        merged.update(values)
        if MODE_KEY in values:
            try:
                self.current_mode_id = int(values[MODE_KEY])
            except (ValueError, TypeError):
                pass
        self._notify_new_keys(merged.keys())
        self._async_push_data(merged)

    @callback
    def _handle_api_response(self, route: str, body: Any, path: str = "") -> None:
        """Take over API responses the UHI broadcasts to all clients."""
        if route.startswith("heatingunit") or route == "data.rapidheating":
            self._handle_heating_unit_response(route, body, path)
            return
        if route.startswith("operationmode"):
            # GET/PUT return the mode object, /list a list (ignored).
            if isinstance(body, dict) and "id" in body:
                self._apply_mode_response(body)
                self.async_update_listeners()
            return
        values: dict[str, Any] = dict(self.data or {})
        if route == "functiondata.groups" and isinstance(body, dict):
            for group_name, items in body.items():
                self._merge_items(values, items, group_name)
        elif route == "functiondata.group":
            self._merge_items(values, body, None)
        elif route == "functiondata.key" and isinstance(body, dict):
            # Writes of any client, e.g. the UHI touch display; these are
            # not part of the change bundles.
            if body.get("key") is None or body.get("value") is None:
                return
            values[body["key"]] = body["value"]
        else:
            return
        self._notify_new_keys(values.keys())
        self._async_push_data(values)

    @callback
    def _handle_heating_unit_response(self, route: str, body: Any, path: str) -> None:
        parts = path_parts(path)
        unit_id = parts[1] if len(parts) >= 3 and parts[0] == "heatingunit" else None
        if route == "heatingunit.config" and isinstance(body, list):
            for config in body:
                if isinstance(config, dict) and config.get("id") in self.heating_units:
                    self._apply_heating_unit_values(
                        str(config["id"]), config.get("variableValues")
                    )
        elif route == "heatingunit.temperature" and unit_id:
            self._apply_heating_unit_values(unit_id, body)
        elif route.endswith("rapidheating") and isinstance(body, dict):
            if body.get("id") is not None and body.get("level") is not None:
                self._apply_heating_unit_values(
                    str(body["id"]), {"rapidheating": {"level": body["level"]}}
                )
        else:
            return
        self.async_update_listeners()

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
        self._async_push_data(data)

    @callback
    def _async_push_data(self, data: dict[str, Any]) -> None:
        """Publish pushed/locally written data without delaying the next poll.

        async_set_updated_data() would reschedule the REST refresh on every
        socket bundle, so with steady pushes the snapshot, version and mode
        polls would never run.
        """
        self.data = data
        self.async_update_listeners()

    @property
    def identifier(self) -> str:
        """Stable identifier for unique ids and the device registry.

        Prefer the entry's unique id (MAC on UHI 4.x, WPM serial number on
        3.x, captured during setup), so a transiently unreadable endpoint at
        startup does not change all entity unique ids.
        """
        return self.entry.unique_id or self.mac or self.entry.entry_id

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
    async def async_set_function_data(self, key: str, value: Any) -> Any:
        """Write a value and return the value confirmed by the UHI."""
        try:
            result = await self.client.set_function_data(key, value)
        except UhiApiError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"key": key, "error": str(exc)},
            ) from exc
        confirmed = result.get("value")
        return value if confirmed is None else confirmed

    async def async_set_operation_mode(self, mode_id: int) -> None:
        extra: dict[str, Any] = {}
        if mode_id in (MODE_HOLIDAY, MODE_PARTY):
            hours = self.entry.options.get(CONF_PARTY_HOURS, DEFAULT_PARTY_HOURS)
            end = dt_util.now() + timedelta(hours=hours)
            extra["dateEnd"] = end.strftime("%Y-%m-%dT%H:%M:%S")
        if self.is_automatic is None:
            # Sending is_automatic_mode=0 blindly would switch automatic off.
            await self._async_refresh_current_mode()
        await self._async_put_mode(mode_id, bool(self.is_automatic), **extra)

    async def async_set_automatic(self, enabled: bool) -> None:
        if self.current_mode_id is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="mode_unknown"
            )
        if self.current_mode_id in (MODE_HOLIDAY, MODE_PARTY):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="automatic_timed_mode"
            )
        await self._async_put_mode(self.current_mode_id, enabled)

    async def async_set_mode_limit(self, field: str, value: float) -> None:
        """Set a limit of the automatic mode switching."""
        if not self.is_automatic:
            # The UHI only applies the limits together with automatic mode.
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="automatic_required"
            )
        if self.current_mode_id is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="mode_unknown"
            )
        if self.current_mode_id in (MODE_HOLIDAY, MODE_PARTY):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="automatic_timed_mode"
            )
        limits = {**self.mode_limits, field: value}
        await self._async_put_mode(self.current_mode_id, True, **limits)
        self.mode_limits[field] = value
        self.async_update_listeners()

    async def async_set_heating_unit_target(self, unit_id: str, value: float) -> None:
        if unit_id == HOT_WATER_UNIT:
            # Same rule as the UHI app: not below the hot water minimum.
            minimum = (self.data or {}).get(WW_MIN_KEY)
            try:
                if minimum is not None and value < float(minimum):
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="ww_below_minimum",
                        translation_placeholders={"minimum": str(minimum)},
                    )
            except (TypeError, ValueError):
                pass
        try:
            result = await self.client.set_heating_unit_target(unit_id, value)
        except UhiApiError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"key": unit_id, "error": str(exc)},
            ) from exc
        self._apply_heating_unit_values(unit_id, {"target": value, **result})
        self.async_update_listeners()

    async def async_set_rapid_heating(self, unit_id: str, level: int) -> None:
        try:
            result = await self.client.set_rapid_heating(unit_id, level)
        except UhiApiError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"key": unit_id, "error": str(exc)},
            ) from exc
        confirmed = result.get("level", level)
        self._apply_heating_unit_values(unit_id, {"rapidheating": {"level": confirmed}})
        self.async_update_listeners()

    async def _async_put_mode(
        self, mode_id: int, is_automatic: bool, **extra: Any
    ) -> None:
        try:
            result = await self.client.set_operation_mode(
                mode_id, is_automatic, **extra
            )
        except UhiApiError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"key": MODE_KEY, "error": str(exc)},
            ) from exc
        self.current_mode_id = mode_id
        self.is_automatic = is_automatic
        self._apply_mode_response(result)
        self.async_update_listeners()
