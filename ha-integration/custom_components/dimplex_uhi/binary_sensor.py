"""Binary sensor platform: 0/1 keys without a unit."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DimplexUhiCoordinator
from .discovery import setup_dynamic_entities
from .entity import DimplexUhiEntity
from .models import PLATFORM_BINARY_SENSOR, resolve_binary_device_class


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    setup_dynamic_entities(
        coordinator, PLATFORM_BINARY_SENSOR, DimplexUhiBinarySensor, async_add_entities
    )


class DimplexUhiBinarySensor(DimplexUhiEntity, BinarySensorEntity):
    """0/1 status sensor for a UHI key."""

    def __init__(self, coordinator: DimplexUhiCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        device_class = resolve_binary_device_class(key)
        if device_class:
            self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        value = self._raw_value
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        try:
            return int(float(value)) != 0
        except (TypeError, ValueError):
            return None
