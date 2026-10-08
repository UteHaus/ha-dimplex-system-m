"""Number platform: writable numeric parameters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DimplexUhiCoordinator
from .entity import DimplexUhiEntity, build_device_info, entity_id_adder
from .models import (
    PLATFORM_NUMBER,
    WRITABLE_SPECS,
    WritableSpec,
    coerce_number,
    resolve_unit_for_key,
)
from .names import label

# Heating unit type -> (German name, English name); {name} is the unit name.
_UNIT_NAMES: dict[str, tuple[str, str]] = {
    "HK_VERSCHIEBUNG": ("{name} Heizkurvenverschiebung", "{name} heating curve shift"),
    "HK_FESTWERT": ("{name} Vorlauf-Solltemperatur", "{name} flow setpoint"),
    "HK_RAUMSTEUERUNG": ("{name} Raum-Solltemperatur", "{name} room setpoint"),
    "RAUMTEMPERATUR": ("{name} Raum-Solltemperatur", "{name} room setpoint"),
    "WARMWASSER": ("Warmwasser-Solltemperatur", "Hot water setpoint"),
    "SCHWIMMBAD": ("Schwimmbad-Solltemperatur", "Pool setpoint"),
}

# Heating units that took over the entity of a former function data number.
LEGACY_UNIT_IDS: dict[str, str] = {"WW": "P_WW_SOLL"}

# operationmode field -> (German, English, unit, min, max)
_MODE_LIMITS: dict[str, tuple[str, str, str, float, float]] = {
    "limitTempHeating": (
        "Automatik Heizgrenze",
        "Automatic heating limit",
        UnitOfTemperature.CELSIUS,
        -30,
        40,
    ),
    "limitTempCooling": (
        "Automatik Kühlgrenze",
        "Automatic cooling limit",
        UnitOfTemperature.CELSIUS,
        -30,
        40,
    ),
    "delayTimeHours": (
        "Automatik Umschaltverzögerung",
        "Automatic switching delay",
        UnitOfTime.HOURS,
        1,
        150,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities = entity_id_adder(coordinator, "number", async_add_entities)
    entities: list[NumberEntity] = [
        DimplexUhiNumber(coordinator, spec)
        for spec in WRITABLE_SPECS.values()
        if spec.platform == PLATFORM_NUMBER
    ]
    entities.extend(
        DimplexUhiHeatingUnitNumber(coordinator, unit_id)
        for unit_id, unit in coordinator.heating_units.items()
        if unit.get("settable") and coordinator.heating_unit_present(unit_id)
    )
    entities.extend(
        DimplexUhiModeLimitNumber(coordinator, field)
        for field in _MODE_LIMITS
        if field in coordinator.mode_limits
    )
    async_add_entities(entities)


class DimplexUhiNumber(DimplexUhiEntity, RestoreNumber):
    """Writable function data parameter (restored until the UHI reports it)."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: DimplexUhiCoordinator, spec: WritableSpec) -> None:
        super().__init__(coordinator, spec.key)
        self._spec = spec
        self._optimistic: float | None = None
        if spec.name:
            self._attr_name = label(self._language, *spec.name)

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

        self._attr_native_step = spec.step if spec.step is not None else 1

    def _range_value(
        self, fallback: float | None, def_field: str, meta_field: str
    ) -> float | None:
        # The UHI does not validate writes, so its own current limits win
        # over the hard-coded spec, then the bundled metadata.
        definition = self._definition
        if definition and definition.get(def_field) is not None:
            return definition[def_field]
        if fallback is not None:
            return fallback
        if self._meta and self._meta.get(meta_field) is not None:
            return self._meta[meta_field]
        return None

    @property
    def native_min_value(self) -> float:
        value = self._range_value(self._spec.min, "numberMin", "minVal")
        return super().native_min_value if value is None else value

    @property
    def native_max_value(self) -> float:
        value = self._range_value(self._spec.max, "numberMax", "maxVal")
        return super().native_max_value if value is None else value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._optimistic = last.native_value

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
        confirmed = coerce_number(
            await self.coordinator.async_set_function_data(self._key, payload)
        )
        self._optimistic = confirmed
        self.coordinator.apply_local_value(self._key, confirmed)


class DimplexUhiHeatingUnitNumber(
    CoordinatorEntity[DimplexUhiCoordinator], NumberEntity
):
    """Setpoint of a heating unit, as adjustable in the UHI app."""

    _attr_has_entity_name = False
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: DimplexUhiCoordinator, unit_id: str) -> None:
        super().__init__(coordinator)
        self._unit_id = unit_id
        unit = coordinator.heating_units[unit_id]
        # Hot water replaces the former P_WW_SOLL number: keep its entity.
        suffix = LEGACY_UNIT_IDS.get(unit_id, f"heatingunit_{unit_id}")
        self._attr_unique_id = f"{coordinator.identifier}_{suffix}"
        self._attr_device_info = build_device_info(coordinator)
        german, english = _UNIT_NAMES.get(
            unit.get("type"), ("{name} Solltemperatur", "{name} setpoint")
        )
        self._attr_name = label(coordinator.language, german, english).format(
            name=unit.get("name") or unit_id
        )
        if unit.get("type") == "HK_VERSCHIEBUNG":
            # Shift of the heating curve, not an absolute temperature.
            self._attr_native_unit_of_measurement = UnitOfTemperature.KELVIN
            self._attr_icon = "mdi:chart-bell-curve-cumulative"
        else:
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_device_class = NumberDeviceClass.TEMPERATURE

    @property
    def _unit(self) -> dict[str, Any]:
        return self.coordinator.heating_units.get(self._unit_id, {})

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and "target" in self._unit

    @property
    def native_min_value(self) -> float:
        value = self._unit.get("min")
        return super().native_min_value if value is None else value

    @property
    def native_max_value(self) -> float:
        value = self._unit.get("max")
        return super().native_max_value if value is None else value

    @property
    def native_step(self) -> float:
        return self._unit.get("step") or 1

    @property
    def native_value(self) -> float | None:
        return self._unit.get("target")

    async def async_set_native_value(self, value: float) -> None:
        payload = int(value) if float(value).is_integer() else value
        await self.coordinator.async_set_heating_unit_target(self._unit_id, payload)


class DimplexUhiModeLimitNumber(CoordinatorEntity[DimplexUhiCoordinator], NumberEntity):
    """Limit of the automatic operation mode switching."""

    _attr_has_entity_name = False
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, coordinator: DimplexUhiCoordinator, field: str) -> None:
        super().__init__(coordinator)
        self._field = field
        german, english, unit, low, high = _MODE_LIMITS[field]
        self._attr_unique_id = f"{coordinator.identifier}_mode_{field}"
        self._attr_device_info = build_device_info(coordinator)
        self._attr_name = label(coordinator.language, german, english)
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        if unit == UnitOfTemperature.CELSIUS:
            self._attr_device_class = NumberDeviceClass.TEMPERATURE

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self._field in self.coordinator.mode_limits
        )

    @property
    def native_value(self) -> float | None:
        return self.coordinator.mode_limits.get(self._field)

    async def async_set_native_value(self, value: float) -> None:
        payload = int(value) if float(value).is_integer() else value
        await self.coordinator.async_set_mode_limit(self._field, payload)
