"""Entity registry migration for entities replaced in 0.2.0 (added in 0.2.1)."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import DimplexUhiCoordinator
from .models import COMMISSIONING_KEYS, EXCLUDED_DISCOVERY_KEYS, WRITABLE_SPECS

_LOGGER = logging.getLogger(__name__)

# Raw heating curve register, replaced by the heating curve shift of the
# heating unit with a different scale: removed, not migrated.
_REMOVED_NUMBERS = ("P_HK1_WK",)


@callback
def async_migrate_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DimplexUhiCoordinator
) -> None:
    """Keep entity ids stable where entities were replaced.

    - Commissioning parameters became read-only: their number/select entity
      is replaced by a sensor with the same object id (number.x -> sensor.x).
    - Entities without a successor and generic sensors of keys that are now
      settings are removed.
    - Entity ids HA generated with the area in front ('keller_...') are
      renamed to the scheme of the other entities.
    """
    ent_reg = er.async_get(hass)
    uid = coordinator.identifier

    def find(domain: str, key: str) -> str | None:
        return ent_reg.async_get_entity_id(domain, DOMAIN, f"{uid}_{key}")

    def remove(entity_id: str) -> None:
        _LOGGER.info("Removing replaced entity %s", entity_id)
        ent_reg.async_remove(entity_id)

    for key in COMMISSIONING_KEYS:
        for domain in ("number", "select"):
            old = find(domain, key)
            if old is None:
                continue
            object_id = old.split(".", 1)[1]
            remove(old)
            target = f"sensor.{object_id}"
            current = find("sensor", key)
            if current is None:
                ent_reg.async_get_or_create(
                    "sensor",
                    DOMAIN,
                    f"{uid}_{key}",
                    config_entry=entry,
                    suggested_object_id=object_id,
                )
            elif current != target and ent_reg.async_get(target) is None:
                ent_reg.async_update_entity(current, new_entity_id=target)

    for key in _REMOVED_NUMBERS:
        if old := find("number", key):
            remove(old)
    for key in (*WRITABLE_SPECS, *EXCLUDED_DISCOVERY_KEYS):
        for domain in ("sensor", "binary_sensor"):
            if old := find(domain, key):
                remove(old)
    # The hot water heating unit took over the P_WW_SOLL number; drop the
    # entity a pre-release created for it under its own unique id.
    if find("number", "P_WW_SOLL") and (duplicate := find("number", "heatingunit_WW")):
        remove(duplicate)

    _strip_area_prefix(hass, ent_reg, entry, coordinator)


@callback
def _strip_area_prefix(
    hass: HomeAssistant,
    ent_reg: er.EntityRegistry,
    entry: ConfigEntry,
    coordinator: DimplexUhiCoordinator,
) -> None:
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, coordinator.identifier)}
    )
    if device is None or device.area_id is None:
        return
    area = ar.async_get(hass).async_get_area(device.area_id)
    if area is None:
        return
    # Only ids exactly as HA generated them: '<area>_<device>_...'.
    prefix = f"{slugify(area.name)}_"
    device_slug = slugify(entry.title)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        domain, object_id = reg_entry.entity_id.split(".", 1)
        if not object_id.startswith(prefix + device_slug):
            continue
        # Next free id like HA itself would pick it ('..._2' if taken).
        target = ent_reg.async_generate_entity_id(
            domain,
            object_id[len(prefix) :],
            current_entity_id=reg_entry.entity_id,
        )
        _LOGGER.info("Renaming %s to %s", reg_entry.entity_id, target)
        ent_reg.async_update_entity(reg_entry.entity_id, new_entity_id=target)
