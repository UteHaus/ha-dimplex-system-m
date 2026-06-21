"""Dimplex System M (UHI) – integration setup."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UhiApiClient
from .config_flow import _build_base_url
from .const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_STATE_INTERVAL,
    CONF_TOKEN,
    CONF_VERSION_INTERVAL,
    DEFAULT_STATE_INTERVAL,
    DEFAULT_VERSION_INTERVAL,
    DOMAIN,
)
from .coordinator import DimplexUhiCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    options = entry.options
    base_url = _build_base_url(data[CONF_HOST], data.get(CONF_PORT))

    session = async_get_clientsession(hass)
    client = UhiApiClient(
        session,
        base_url,
        token=data.get(CONF_TOKEN) or None,
        device_id=data.get(CONF_DEVICE_ID) or None,
    )

    coordinator = DimplexUhiCoordinator(
        hass,
        entry,
        client,
        state_interval=options.get(CONF_STATE_INTERVAL, DEFAULT_STATE_INTERVAL),
        version_interval=options.get(
            CONF_VERSION_INTERVAL, DEFAULT_VERSION_INTERVAL
        ),
    )

    await coordinator.async_prepare()
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_connect_socket(base_url)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: DimplexUhiCoordinator | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if coordinator is not None:
        await coordinator.client.disconnect_socket()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on option change (language/intervals)."""
    await hass.config_entries.async_reload(entry.entry_id)
