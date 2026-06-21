"""Optional loader for external/communicator/config/deviceKeys.json.

Enriches entities with metadata (desc, minVal, maxVal, intFac) without
overwriting fields that are already set. The file is not strictly
required; the curated entities already carry sensible defaults.
Enabled via the environment variable DEVICE_KEYS_PATH.

Additionally, sensor entities can be generated automatically from the file
for all keys with "monitor": true (generate_sensor_entities).
"""

from __future__ import annotations

import json
import logging
import os
import re

from .entities import Entity

logger = logging.getLogger("uhi-ha-bridge.device_keys")

_cache: dict | None = None
_names_cache: dict | None = None

# Mapping of UHI units to HA-compliant units.
_UNIT_MAP = {
    "UNIT_DEG_C": "°C",
    "UNIT_DEG_KELVIN": "K",
    "NO_UNIT": None,
    None: None,
}

_WS = re.compile(r"\s+")

# Abbreviation dictionary for the fallback humanizer (keys lowercased).
# Ambiguous abbreviations (e.g. DI/DO as weekday vs. digital in/out) are
# deliberately NOT expanded, to avoid mislabeling.
_ABBREV_DE = {
    "a": "Ausgang", "e": "Eingang", "p": "Parameter",
    "bs": "Betriebsstunden", "ba": "Betriebsart", "anz": "Anzeige",
    "biv": "Bivalenz", "hk": "Heizkreis", "hzk": "Heizkreis",
    "hk1": "Heizkreis 1", "hk2": "Heizkreis 2", "hk3": "Heizkreis 3",
    "h1": "Heizkreis 1", "h2": "Heizkreis 2", "h3": "Heizkreis 3",
    "mi": "Mischer", "mia": "Mischer auf", "miz": "Mischer zu",
    "mir": "Mischer", "m1": "Mischer 1", "m2": "Mischer 2",
    "vd": "Verdichter", "vd1": "Verdichter 1", "vd2": "Verdichter 2",
    "hup": "Heizungsumwälzpumpe", "zup": "Zusatzpumpe",
    "wup": "Warmwasserpumpe", "zwup": "Zirkulationspumpe",
    "sup": "Schwimmbadpumpe", "pup": "Pufferpumpe", "pupk": "Pufferpumpe",
    "zwe": "Zweiter Wärmeerzeuger", "ven": "Ventilator",
    "vent": "Ventilation", "fh": "Flanschheizung", "stf": "Störmeldung",
    "raum": "Raum", "soll": "Sollwert", "ist": "Istwert",
    "temp": "Temperatur", "t": "Temperatur", "ww": "Warmwasser",
    "vorl": "Vorlauf", "rueckl": "Rücklauf", "aussen": "Außen",
    "fuehl": "Fühler", "zeit": "Zeit", "zust": "Zustand",
    "tht": "Thermisches Ventil", "ventil": "Ventil", "aktiv": "aktiv",
    "frei": "Freigabe", "code": "Code", "status": "Status",
    "timeprogram": "Zeitprogramm", "runtime": "Laufzeit",
    "hour": "Stunde", "minute": "Minute", "level": "Stufe",
    "flow": "Durchfluss", "supply": "Zuluft", "exhaust": "Abluft",
    "bypass": "Bypass", "zp": "Zeitprogramm", "st": "Start",
    "end": "Ende", "wmz": "Wärmemengenzähler", "zirk": "Zirkulation",
    "wp": "Wärmepumpe", "sp": "Speicher", "set": "Sollwert",
    "date": "Datum", "new": "Neu", "mon": "Montag", "tue": "Dienstag",
    "wed": "Mittwoch", "thu": "Donnerstag", "fri": "Freitag",
    "sat": "Samstag", "sun": "Sonntag",
}


def _humanize_key(key: str) -> str:
    """Build a readable DE name from a key (abbreviation expansion)."""
    parts: list[str] = []
    for token in re.split(r"[_]+", key):
        if not token:
            continue
        low = token.lower()
        if low in _ABBREV_DE:
            parts.append(_ABBREV_DE[low])
        elif token.isdigit():
            parts.append(token)
        elif token.isupper() or token.islower():
            parts.append(token.capitalize())
        else:
            parts.append(token)
    text = _WS.sub(" ", " ".join(parts)).strip()
    deduped: list[str] = []
    for word in text.split(" "):
        if not deduped or deduped[-1].lower() != word.lower():
            deduped.append(word)
    return " ".join(deduped) or key


def _load_names() -> dict:
    """Load an optional name file (key -> plain text) via NAMES_PATH."""
    global _names_cache
    if _names_cache is not None:
        return _names_cache
    _names_cache = {}
    path = os.environ.get("NAMES_PATH")
    if not path:
        return _names_cache
    try:
        with open(path, encoding="utf-8") as fh:
            _names_cache = json.load(fh)
        logger.info("Name file loaded (%d entries) from %s", len(_names_cache), path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Name file not loadable (%s): %s", path, exc)
        _names_cache = {}
    return _names_cache


def _resolve_name(key: str, desc: str | None) -> str:
    """Readable name: name file -> usable desc -> humanized key."""
    names = _load_names()
    if key in names and names[key]:
        return names[key]
    if desc and desc != key:
        return desc
    return _humanize_key(key)



def _load(path: str | None) -> dict:
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    if not path:
        logger.debug("DEVICE_KEYS_PATH not set - using entity defaults")
        return _cache
    try:
        with open(path, encoding="utf-8") as fh:
            _cache = json.load(fh)
        logger.info("deviceKeys.json loaded (%d entries) from %s", len(_cache), path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("deviceKeys.json not loadable (%s): %s", path, exc)
        _cache = {}
    return _cache


def enrich(entity: Entity, path: str | None) -> Entity:
    meta = _load(path).get(entity.key)
    if not meta:
        return entity
    if entity.min is None and isinstance(meta.get("minVal"), (int, float)):
        entity.min = meta["minVal"]
    if entity.max is None and isinstance(meta.get("maxVal"), (int, float)):
        entity.max = meta["maxVal"]
    if not entity.name:
        entity.name = _resolve_name(entity.key, meta.get("desc"))
    # Note: NO intFac scaling. Via socket and /api/functiondata/groups UHI
    # already provides display-ready values (e.g. 22.2).
    return entity


def _entity_id(key: str) -> str:
    """Build an HA-compatible entity id from a UHI key."""
    return re.sub(r"[^a-z0-9_]+", "_", key.lower()).strip("_")


def _build_sensor_entity(key: str, meta: dict | None) -> Entity:
    """Build a sensor entity from the (optional) metadata of a key."""
    meta = meta or {}
    unit = _UNIT_MAP.get(meta.get("unit"))
    device_class = "temperature" if unit == "°C" else None
    name = _resolve_name(key, meta.get("desc"))
    # scale stays 1.0: values are already display-ready (no intFac division).
    return Entity(
        id=_entity_id(key),
        key=key,
        type="sensor",
        read_source="socket",
        name=name,
        device_class=device_class,
        unit=unit,
    )


def build_entity_for_key(key: str, path: str | None) -> Entity:
    """Build a sensor entity for a single key (even without metadata)."""
    return _build_sensor_entity(key, _load(path).get(key))


def generate_sensor_entities(
    path: str | None, exclude_keys: set[str] | None = None
) -> list[Entity]:
    """Generate sensor entities for all keys with "monitor": true.

    Keys that are already curated (exclude_keys) are skipped.
    Returns an empty list if deviceKeys.json is not available.
    """
    data = _load(path)
    if not data:
        return []
    exclude = exclude_keys or set()
    entities: list[Entity] = []
    seen_ids: set[str] = set()
    for key, meta in data.items():
        if key in exclude or not meta.get("monitor"):
            continue
        entity_id = _entity_id(key)
        if not entity_id or entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)
        entities.append(_build_sensor_entity(key, meta))
    logger.info("%d sensor entities generated from deviceKeys.json", len(entities))
    return entities
