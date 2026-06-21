"""Load and resolve readable entity names (multilingual)."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from .const import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

_LOGGER = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=None)
def _load_names(language: str) -> dict[str, str]:
    path = _DATA_DIR / f"names_{language}.json"
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        _LOGGER.warning("Name file %s not loadable: %s", path, exc)
        return {}


@lru_cache(maxsize=1)
def _load_device_keys() -> dict[str, dict]:
    path = _DATA_DIR / "device_keys.json"
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        _LOGGER.warning("device_keys.json not loadable: %s", exc)
        return {}


def normalize_language(language: str | None) -> str:
    if language and language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


def device_keys() -> dict[str, dict]:
    """Bundled deviceKeys metadata (fallback source)."""
    return _load_device_keys()


def _humanize(key: str) -> str:
    text = re.sub(r"^[A-Z]_", "", key)
    text = text.replace("_", " ")
    return text.strip() or key


def resolve_name(key: str, language: str, meta: dict | None = None) -> str:
    """Return the readable name: i18n -> deviceKeys.desc -> humanized key."""
    names = _load_names(normalize_language(language))
    if key in names:
        return names[key]
    if meta and meta.get("desc") and meta["desc"] != key:
        return meta["desc"]
    return _humanize(key)


def resolve_option_label(key: str, value: str, language: str) -> str:
    """Return the label of a select option (e.g. P_EVS.1)."""
    names = _load_names(normalize_language(language))
    return names.get(f"{key}.{value}", value)
