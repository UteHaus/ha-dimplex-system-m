"""Select platform: operation mode and P_EVS."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DimplexUhiCoordinator
from .entity import DimplexUhiEntity
from .models import PLATFORM_SELECT, WRITABLE_SPECS, WritableSpec, coerce_number
from .names import resolve_option_label


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DimplexUhiCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []
    for spec in WRITABLE_SPECS.values():
        if spec.platform != PLATFORM_SELECT:
            continue
        if spec.write_via == "operationmode":
            entities.append(DimplexUhiModeSelect(coordinator, spec))
        else:
            entities.append(DimplexUhiOptionSelect(coordinator, spec))
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


class DimplexUhiOptionSelect(DimplexUhiEntity, SelectEntity):
    """Selection with a fixed value list (e.g. P_EVS), optimistic."""

    def __init__(self, coordinator: DimplexUhiCoordinator, spec: WritableSpec) -> None:
        super().__init__(coordinator, spec.key)
        self._spec = spec
        self._optimistic: str | None = None
        self._label_to_value = {
            resolve_option_label(spec.key, value, self._language): value
            for value in spec.option_values
        }
        self._value_to_label = {v: k for k, v in self._label_to_value.items()}

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def options(self) -> list[str]:
        return list(self._label_to_value)

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        if self._key in data:
            raw = coerce_number(data[self._key])
            value = str(int(raw)) if isinstance(raw, (int, float)) else str(raw)
            return self._value_to_label.get(value)
        if self._optimistic is not None:
            return self._value_to_label.get(self._optimistic)
        return None

    async def async_select_option(self, option: str) -> None:
        value = self._label_to_value.get(option)
        if value is None:
            return
        await self.coordinator.async_set_function_data(self._key, int(value))
        self._optimistic = value
        self.coordinator.apply_local_value(self._key, int(value))
