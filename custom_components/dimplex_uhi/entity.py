"""Shared base class and device info for entities."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import DimplexUhiCoordinator
from .models import is_curated
from .names import device_keys, resolve_name


def build_device_info(coordinator: DimplexUhiCoordinator) -> DeviceInfo:
    entry = coordinator.entry
    uhi = coordinator.version.get("uhi") or {}
    info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.identifier)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.title,
    )
    if uhi.get("version"):
        info["sw_version"] = uhi["version"]
    if coordinator.mac:
        info["connections"] = {("mac", coordinator.mac)}
    return info


def suggested_object_id(coordinator: DimplexUhiCoordinator, name: str) -> str:
    """'<device name> <entity name>', e.g. 'dimplex_system_m_smart_grid'."""
    return slugify(f"{coordinator.entry.title} {name}")


def entity_id_adder(
    coordinator: DimplexUhiCoordinator,
    domain: str,
    async_add_entities: AddEntitiesCallback,
) -> AddEntitiesCallback:
    """Wrap async_add_entities to suggest entity ids without the area.

    Since HA 2026.10 new entities get the area in front ('keller_...'); keep
    the scheme of the existing entities. Only used for new registry entries,
    existing entity ids are not changed.
    """

    @callback
    def _add(entities: Iterable[Entity], update_before_add: bool = False) -> None:
        entities = list(entities)
        for entity in entities:
            name = entity.name
            if entity.entity_id is None and isinstance(name, str):
                entity.entity_id = f"{domain}.{suggested_object_id(coordinator, name)}"
        async_add_entities(entities, update_before_add)

    return _add


class DimplexUhiEntity(CoordinatorEntity[DimplexUhiCoordinator]):
    """Base class for all UHI entities."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: DimplexUhiCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._language = coordinator.language
        self._meta = device_keys().get(key)
        self._attr_unique_id = f"{coordinator.identifier}_{key}"
        self._attr_device_info = build_device_info(coordinator)
        self._attr_name = resolve_name(key, self._language, self._meta)
        if not is_curated(key, coordinator.key_group.get(key)):
            self._attr_entity_registry_enabled_default = False
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def _definition(self) -> dict | None:
        return self.coordinator.definitions.get(self._key)

    @property
    def _raw_value(self) -> Any:
        data = self.coordinator.data or {}
        return data.get(self._key)

    @property
    def available(self) -> bool:
        return super().available and self._key in (self.coordinator.data or {})
