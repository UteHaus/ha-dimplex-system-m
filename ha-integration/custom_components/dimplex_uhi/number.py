"""Number platform: writable numeric parameters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DimplexUhiCoordinator
from .entity import DimplexUhiEntity
from .models import (
    PLATFORM_NUMBER,
    WRITABLE_SPECS,
    WritableSpec,
    coerce_number,
    resolve_unit_for_key,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        DimplexUhiNumber(coordinator, spec)
        for spec in WRITABLE_SPECS.values()
        if spec.platform == PLATFORM_NUMBER
    ]
    async_add_entities(entities)


class DimplexUhiNumber(DimplexUhiEntity, NumberEntity):
    """Writable numeric parameter (optimistic if not readable)."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: DimplexUhiCoordinator, spec: WritableSpec) -> None:
        super().__init__(coordinator, spec.key)
        self._spec = spec
        self._optimistic: float | None = None

        unit = spec.unit or resolve_unit_for_key(
            self._key, self._definition, self._meta
        )
        if unit == "°C":
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif unit == "K":
            self._attr_native_unit_of_measurement = UnitOfTemperature.KELVIN
        elif unit:
            self._attr_native_unit_of_measurement = unit
        if spec.device_class:
            self._attr_device_class = spec.device_class

        self._attr_native_min_value = self._range_value(spec.min, "numberMin", "minVal")
        self._attr_native_max_value = self._range_value(spec.max, "numberMax", "maxVal")
        self._attr_native_step = spec.step if spec.step is not None else 1

    def _range_value(
        self, override: float | None, def_field: str, meta_field: str
    ) -> float | None:
        if override is not None:
            return override
        definition = self._definition
        if definition and definition.get(def_field) is not None:
            return definition[def_field]
        if self._meta and self._meta.get(meta_field) is not None:
            return self._meta[meta_field]
        return None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        if self._key in data:
            value = data[self._key]
            num = coerce_number(value)
            return num if isinstance(num, (int, float)) else None
        return self._optimistic

    async def async_set_native_value(self, value: float) -> None:
        payload = int(value) if float(value).is_integer() else value
        await self.coordinator.async_set_function_data(self._key, payload)
        self._optimistic = value
        self.coordinator.apply_local_value(self._key, payload)
