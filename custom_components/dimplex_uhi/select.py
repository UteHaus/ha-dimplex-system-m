"""Select platform: operation mode and rapid heating."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DimplexUhiCoordinator
from .entity import DimplexUhiEntity, build_device_info, entity_id_adder
from .models import (
    PLATFORM_SELECT,
    WRITABLE_SPECS,
    WritableSpec,
)
from .names import label

RAPID_HEATING_LEVELS = (0, 1, 2, 3)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities = entity_id_adder(coordinator, "select", async_add_entities)
    entities: list[SelectEntity] = [
        DimplexUhiModeSelect(coordinator, spec)
        for spec in WRITABLE_SPECS.values()
        if spec.platform == PLATFORM_SELECT and spec.write_via == "operationmode"
    ]
    entities.extend(
        DimplexUhiRapidHeatingSelect(coordinator, unit_id)
        for unit_id, unit in coordinator.heating_units.items()
        if "rapidheating" in unit
    )
    async_add_entities(entities)


class DimplexUhiModeSelect(DimplexUhiEntity, SelectEntity):
    """Operation mode selection (BA_aktiv) via the operationmode API."""

    def __init__(self, coordinator: DimplexUhiCoordinator, spec: WritableSpec) -> None:
        super().__init__(coordinator, spec.key)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and bool(
            self.coordinator.mode_names
        )

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.mode_names)

    @property
    def current_option(self) -> str | None:
        mode_id = self.coordinator.current_mode_id
        if mode_id is None:
            return None
        return self.coordinator.mode_id_to_name.get(mode_id)

    async def async_select_option(self, option: str) -> None:
        mode_id = self.coordinator.mode_name_to_id.get(option)
        if mode_id is None:
            return
        await self.coordinator.async_set_operation_mode(mode_id)


class DimplexUhiRapidHeatingSelect(
    CoordinatorEntity[DimplexUhiCoordinator], SelectEntity
):
    """Rapid heating level (0 = off .. 3) of a heating circuit."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: DimplexUhiCoordinator, unit_id: str) -> None:
        super().__init__(coordinator)
        self._unit_id = unit_id
        language = coordinator.language
        unit_name = coordinator.heating_units[unit_id].get("name") or unit_id
        self._attr_unique_id = f"{coordinator.identifier}_rapidheating_{unit_id}"
        self._attr_device_info = build_device_info(coordinator)
        self._attr_name = label(
            language,
            f"{unit_name} Schnellaufheizung",
            f"{unit_name} rapid heating",
        )
        self._level_to_option = {
            level: label(language, "Aus", "Off")
            if level == 0
            else label(language, f"Stufe {level}", f"Level {level}")
            for level in RAPID_HEATING_LEVELS
        }
        self._option_to_level = {v: k for k, v in self._level_to_option.items()}
        self._attr_options = list(self._option_to_level)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and (
            "rapidheating" in self.coordinator.heating_units.get(self._unit_id, {})
        )

    @property
    def current_option(self) -> str | None:
        unit = self.coordinator.heating_units.get(self._unit_id, {})
        return self._level_to_option.get(unit.get("rapidheating"))

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_rapid_heating(
            self._unit_id, self._option_to_level[option]
        )
