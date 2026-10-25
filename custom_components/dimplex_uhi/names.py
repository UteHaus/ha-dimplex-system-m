"""Load and resolve readable entity names (multilingual)."""

from __future__ import annotations

from functools import cache
import json
import logging
from pathlib import Path
import re

from .const import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

_LOGGER = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"


@cache
def _load_json(name: str) -> dict:
    path = _DATA_DIR / name
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        _LOGGER.warning("%s not loadable: %s", path, exc)
        return {}


def _load_names(language: str) -> dict[str, str]:
    return _load_json(f"names_{language}.json")


def normalize_language(language: str | None) -> str:
    if language and language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


def preload(language: str) -> None:
    """Load the data files (blocking I/O; run in the executor at setup)."""
    _load_names(normalize_language(language))
    device_keys()


def device_keys() -> dict[str, dict]:
    """Bundled deviceKeys metadata (fallback source)."""
    return _load_json("device_keys.json")


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


def label(language: str, german: str, english: str) -> str:
    """Pick the German or English text for names the UHI does not provide."""
    return german if normalize_language(language) == "de" else english


def resolve_option_label(key: str, value: str, language: str) -> str:
    """Return the label of a select option (e.g. P_EVS.1)."""
    names = _load_names(normalize_language(language))
    return names.get(f"{key}.{value}", value)
