"""Sensor platform: all numeric/textual read keys."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DimplexUhiCoordinator
from .discovery import setup_dynamic_entities
from .entity import DimplexUhiEntity, build_device_info
from .models import (
    ENERGY_POWER_KEY,
    PLATFORM_SENSOR,
    coerce_number,
    resolve_sensor_classes,
    resolve_unit_for_key,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    setup_dynamic_entities(
        coordinator, PLATFORM_SENSOR, DimplexUhiSensor, async_add_entities
    )
    async_add_entities([DimplexUhiEnergySensor(coordinator)])


class DimplexUhiSensor(DimplexUhiEntity, SensorEntity):
    """Read-only sensor for a UHI key."""

    def __init__(self, coordinator: DimplexUhiCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        unit = resolve_unit_for_key(self._key, self._definition, self._meta)
        if unit:
            self._attr_native_unit_of_measurement = unit
        device_class, state_class = resolve_sensor_classes(unit)
        if device_class:
            self._attr_device_class = device_class
        self._unit_state_class = state_class

    @property
    def native_value(self) -> Any:
        value = self._raw_value
        if isinstance(value, bool):
            return value
        # Convert numeric strings to a number, otherwise keep the original.
        return coerce_number(value)

    @property
    def state_class(self) -> SensorStateClass | None:
        # Prefer the class derived from the unit.
        if self._unit_state_class:
            return SensorStateClass(self._unit_state_class)
        value = self._raw_value
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return SensorStateClass.MEASUREMENT
        try:
            float(value)
        except (TypeError, ValueError):
            return None
        return SensorStateClass.MEASUREMENT


class DimplexUhiEnergySensor(CoordinatorEntity[DimplexUhiCoordinator], RestoreSensor):
    """Derived energy meter: integrates AC power input over time.

    Provides kWh (total_increasing) for the Home Assistant Energy dashboard.
    The meter value is restored across restarts.
    """

    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator: DimplexUhiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.identifier}_ac_input_energy"
        self._attr_device_info = build_device_info(coordinator)
        self._attr_name = (
            "Stromverbrauch"
            if coordinator.language == "de"
            else "Power consumption"
        )
        self._energy_kwh: float = 0.0
        self._last_power: float | None = None
        self._last_ts: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value is not None:
            try:
                self._energy_kwh = float(last.native_value)
            except (TypeError, ValueError):
                self._energy_kwh = 0.0

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        raw = data.get(ENERGY_POWER_KEY)
        try:
            power = float(raw)
        except (TypeError, ValueError):
            return
        now = time.monotonic()
        if self._last_power is not None and self._last_ts is not None:
            dt = now - self._last_ts
            # Plausibility: only integrate sensible intervals.
            if 0 < dt < 3600:
                avg_power = (power + self._last_power) / 2.0
                # W * s -> kWh
                self._energy_kwh += avg_power * dt / 3_600_000.0
        self._last_power = power
        self._last_ts = now
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float:
        return round(self._energy_kwh, 6)
