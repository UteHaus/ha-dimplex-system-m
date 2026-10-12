"""Update platform: UHI software version and the UHI's own online update.

Uses the endpoints behind the "Update" button of the UHI web UI:
GET /api/system/update/check (the UHI asks the vendor server),
PUT /api/system/update (start) and GET /api/system/update (progress). The
updater also broadcasts its progress as 'api.response' with route
'system.update' (see coordinator).

Before installing, the offered version is compared with TESTED_UHI_VERSION,
the newest UHI version this integration release was tested with: a newer
major version is blocked, a newer minor/patch version only shows a warning.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import re
import time
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.loader import async_get_integration

from .api import UhiApiError
from .const import DOMAIN, TESTED_UHI_VERSION
from .coordinator import DimplexUhiCoordinator
from .entity import build_device_info, entity_id_adder

_LOGGER = logging.getLogger(__name__)

# The check makes the UHI contact the vendor server; new versions are rare.
CHECK_INTERVAL = timedelta(days=2)
# Until a check succeeded (e.g. while the UHI has no internet), try hourly.
RETRY_INTERVAL = timedelta(hours=1)
# The UHI updater picks up a request every 10 s.
STATUS_INTERVAL = timedelta(seconds=10)

# Status codes of the UHI updater (app/actions/run-updater.js).
CODE_UHI_RUNNING = 10
CODE_DISABLED = 1
# 'latest.version' the UHI 4.x reports when the vendor server did not answer;
# UHI 3.x reports 'latest: null' instead.
FAILED_CHECK_VERSION = "0.0.0"

NAMES = {"de": "UHI-Software", "en": "UHI software"}

COMPATIBLE = "compatible"
WARN = "warn"
BLOCK = "block"

# Shown as release summary (max. 255 characters) and as install error.
MESSAGES = {
    "de": {
        WARN: (
            "Achtung: UHI {latest} ist neuer als die Version {tested}, mit der "
            "die Integration dimplex_uhi {integration} getestet ist. Nach dem "
            "Update können Entitäten fehlen oder sich ändern."
        ),
        BLOCK: (
            "UHI {latest} ist eine neue Hauptversion; die Integration "
            "dimplex_uhi {integration} ist nur mit UHI {tested} getestet. "
            "Installation über Home Assistant gesperrt – erst die Integration "
            "aktualisieren."
        ),
    },
    "en": {
        WARN: (
            "Caution: UHI {latest} is newer than version {tested} the "
            "dimplex_uhi {integration} integration was tested with. Entities "
            "may be missing or change after the update."
        ),
        BLOCK: (
            "UHI {latest} is a new major version; the dimplex_uhi {integration} "
            "integration is only tested with UHI {tested}. Installation from "
            "Home Assistant is blocked – update the integration first."
        ),
    },
}

_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(version: str | None) -> tuple[int, int, int] | None:
    """'4.3.4' -> (4, 3, 4); None if it does not start with a number."""
    match = _VERSION_RE.match(version or "")
    if not match:
        return None
    major, minor, patch = (int(part or 0) for part in match.groups())
    return major, minor, patch


def compatibility(version: str | None, tested: str = TESTED_UHI_VERSION) -> str:
    """COMPATIBLE, WARN (newer minor/patch, unknown) or BLOCK (newer major)."""
    offered, known = parse_version(version), parse_version(tested)
    if offered is None or known is None:
        return WARN
    if offered <= known:
        return COMPATIBLE
    if offered[0] > known[0]:
        return BLOCK
    return WARN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities = entity_id_adder(coordinator, "update", async_add_entities)
    async_add_entities([DimplexUhiUpdate(coordinator)])


class DimplexUhiUpdate(CoordinatorEntity[DimplexUhiCoordinator], UpdateEntity):
    """Installed and offered UHI version; installs the vendor update."""

    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG
    # The UHI may reboot its controller after an update; opt in explicitly.
    _attr_entity_registry_enabled_default = False
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    def __init__(self, coordinator: DimplexUhiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.identifier}_uhi_update"
        self._attr_device_info = build_device_info(coordinator)
        self._attr_name = NAMES.get(coordinator.language, NAMES["en"])
        self._check: dict[str, Any] = {}
        self._last_check: float | None = None
        self._unsub_status: CALLBACK_TYPE | None = None
        self._integration_version = "?"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        integration = await async_get_integration(self.hass, DOMAIN)
        if integration.version:
            self._integration_version = str(integration.version)
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_check, RETRY_INTERVAL)
        )
        self.async_on_remove(self._stop_status_polling)
        await self._async_check()

    # ---------------- State ----------------
    @property
    def installed_version(self) -> str | None:
        version = (self.coordinator.version.get("uhi") or {}).get("version")
        return str(version) if version else None

    @property
    def latest_version(self) -> str | None:
        latest = (self._check.get("latest") or {}).get("version")
        if self._check.get("available") and latest:
            return str(latest)
        return self.installed_version

    @property
    def release_summary(self) -> str | None:
        latest = self.latest_version
        if latest is None or latest == self.installed_version:
            return None
        return self._compatibility_message(latest)

    def _compatibility_message(self, version: str) -> str | None:
        level = compatibility(version)
        if level == COMPATIBLE:
            return None
        texts = MESSAGES.get(self.coordinator.language, MESSAGES["en"])
        return texts[level].format(
            latest=version,
            tested=TESTED_UHI_VERSION,
            integration=self._integration_version,
        )

    @property
    def in_progress(self) -> bool:
        return self._status.get("code") == CODE_UHI_RUNNING

    @property
    def update_percentage(self) -> int | None:
        if not self.in_progress:
            return None
        current = self._status.get("current_step_no")
        total = self._status.get("total_step_no")
        if not isinstance(current, int) or not isinstance(total, int) or total <= 0:
            return None
        return min(100, round(current * 100 / total))

    @property
    def _status(self) -> dict[str, Any]:
        return self.coordinator.update_status

    @callback
    def _handle_coordinator_update(self) -> None:
        # Progress broadcasts arrive without our polling (e.g. an update
        # started on the display); poll until the update has finished.
        if self.in_progress:
            self._start_status_polling()
        super()._handle_coordinator_update()

    # ---------------- Actions ----------------
    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        # The UHI always installs the newest version the vendor offers.
        offered = self.latest_version
        level = compatibility(offered)
        if level == BLOCK:
            raise HomeAssistantError(self._compatibility_message(offered))
        if level == WARN:
            _LOGGER.warning(
                "Installing UHI %s, not tested with dimplex_uhi %s (tested: UHI %s)",
                offered,
                self._integration_version,
                TESTED_UHI_VERSION,
            )
        try:
            status = await self.coordinator.client.start_update()
        except UhiApiError as exc:
            raise HomeAssistantError(f"UHI update could not be started: {exc}") from exc
        if status.get("code") == CODE_DISABLED:
            raise HomeAssistantError(
                "Updates are disabled on the UHI (system.update.enabled)"
            )
        self.coordinator.update_status = status or {"code": CODE_UHI_RUNNING}
        self._start_status_polling()
        self.async_write_ha_state()

    # ---------------- Polling ----------------
    async def _async_check(self, _now: Any = None, force: bool = False) -> None:
        """Ask for a new UHI version every CHECK_INTERVAL, if online."""
        if (
            not force
            and self._last_check is not None
            and time.monotonic() - self._last_check < CHECK_INTERVAL.total_seconds()
        ):
            return
        client = self.coordinator.client
        try:
            # Without internet the UHI answers with a dummy 'no update'.
            if not (await client.get_system_status()).get("has_internet"):
                _LOGGER.debug("UHI has no internet; update check skipped")
                return
            data = await client.get_update_check()
        except UhiApiError as exc:
            _LOGGER.debug("UHI update check failed: %s", exc)
            return
        # UHI 4.x: { oldRemoteUpdateStatus: {...}, applianceFirmwareUpdateStatus },
        # UHI 3.x: the vendor answer itself.
        check = data.get("oldRemoteUpdateStatus", data)
        if not isinstance(check, dict):
            return
        latest = check.get("latest")
        if not isinstance(latest, dict) or latest.get("version") in (
            None,
            FAILED_CHECK_VERSION,
        ):
            _LOGGER.debug("UHI could not reach the vendor server")
            return
        self._check = check
        self._last_check = time.monotonic()
        self.async_write_ha_state()

    @callback
    def _start_status_polling(self) -> None:
        if self._unsub_status is None:
            self._unsub_status = async_track_time_interval(
                self.hass, self._async_poll_status, STATUS_INTERVAL
            )

    @callback
    def _stop_status_polling(self) -> None:
        if self._unsub_status is not None:
            self._unsub_status()
            self._unsub_status = None

    async def _async_poll_status(self, _now: Any = None) -> None:
        try:
            status = await self.coordinator.client.get_update_status()
        except UhiApiError as exc:
            # The UHI restarts at the end of an update.
            _LOGGER.debug("UHI update status not readable: %s", exc)
            return
        self.coordinator.update_status = status
        if not self.in_progress:
            self._stop_status_polling()
            # New version after a successful update; the check then
            # reports no further update.
            await self.coordinator._async_refresh_version()
            await self._async_check(force=True)
        self.async_write_ha_state()
