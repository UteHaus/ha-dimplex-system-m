"""Helper to dynamically create sensor/binary-sensor entities."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DimplexUhiCoordinator
from .models import WRITABLE_SPECS, classify_platform
from .names import device_keys


@callback
def setup_dynamic_entities(
    coordinator: DimplexUhiCoordinator,
    platform: str,
    factory: Callable[[DimplexUhiCoordinator, str], object],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create entities for all currently/newly known keys of this platform."""
    added: set[str] = set()
    keys_meta = device_keys()

    @callback
    def _add(keys: Iterable[str]) -> None:
        new_entities = []
        for key in keys:
            if key in added or key in WRITABLE_SPECS:
                continue
            meta = keys_meta.get(key)
            definition = coordinator.definitions.get(key)
            if classify_platform(key, definition, meta) != platform:
                continue
            added.add(key)
            new_entities.append(factory(coordinator, key))
        if new_entities:
            async_add_entities(new_entities)

    _add(sorted(coordinator.known_keys))
    coordinator.add_new_key_listener(_add)
