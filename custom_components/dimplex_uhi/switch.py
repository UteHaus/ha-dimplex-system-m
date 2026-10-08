"""Switch platform: automatic operation-mode switching (P_TBaUs)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DimplexUhiCoordinator
from .entity import build_device_info, entity_id_adder
from .names import resolve_name

AUTOMATIC_KEY = "P_TBaUs"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities = entity_id_adder(coordinator, "switch", async_add_entities)
    async_add_entities([DimplexUhiAutomaticSwitch(coordinator)])


class DimplexUhiAutomaticSwitch(CoordinatorEntity[DimplexUhiCoordinator], SwitchEntity):
    """Automatic summer/winter switching, set via the operationmode API."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:sun-snowflake-variant"

    def __init__(self, coordinator: DimplexUhiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.identifier}_{AUTOMATIC_KEY}"
        self._attr_device_info = build_device_info(coordinator)
        self._attr_name = resolve_name(AUTOMATIC_KEY, coordinator.language)

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.is_automatic is not None
        )

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.is_automatic

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_automatic(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_automatic(False)
