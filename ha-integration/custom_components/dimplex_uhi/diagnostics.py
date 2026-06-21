"""Diagnostics data for the Dimplex System M (UHI) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, CONF_TOKEN, DOMAIN
from .coordinator import DimplexUhiCoordinator

TO_REDACT = {CONF_TOKEN, CONF_DEVICE_ID, "mac"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "version": async_redact_data(coordinator.version, TO_REDACT),
        "known_key_count": len(coordinator.known_keys),
        "mode_names": coordinator.mode_names,
        "current_mode_id": coordinator.current_mode_id,
        "data": coordinator.data,
    }
