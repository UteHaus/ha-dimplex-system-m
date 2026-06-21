#!/usr/bin/env python3
"""Extrahiert lesbare Namen aus den UHI-i18n-Dateien und bündelt deviceKeys.json.

Erzeugt:
  ha-integration/custom_components/dimplex_uhi/data/names_de.json
  ha-integration/custom_components/dimplex_uhi/data/names_en.json
  ha-integration/custom_components/dimplex_uhi/data/device_keys.json

Quellen (relativ zum Repo-Root):
  DE: uhi/config/i18n/de/de.common.json + de.easyon.json
  EN: uhi/config/i18n/en-us/en-us.common.json + en-us.easyon.json
  deviceKeys: uhi/external/communicator/config/deviceKeys.json

Aufruf (aus dem Repo-Root dimplex-ha-system-m/):
  python tools/extract_names.py [--uhi-root ../uhi]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Soft-Hyphen (HTML-Entity und Unicode) sowie einfache HTML-Tags entfernen.
_SHY_ENTITY = re.compile(r"&shy;?")
_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


# Abkürzungs-Wörterbücher für den Fallback-Humanizer (Keys kleingeschrieben).
# Damit erhalten auch Keys ohne i18n-Eintrag einen lesbaren Namen.
# Mehrdeutige Kürzel (z. B. DI/DO als Wochentag vs. Digital In/Out) werden
# bewusst NICHT expandiert, um Falschbenennungen zu vermeiden.
_ABBREV_DE: dict[str, str] = {
    "a": "Ausgang",
    "e": "Eingang",
    "p": "Parameter",
    "bs": "Betriebsstunden",
    "ba": "Betriebsart",
    "anz": "Anzeige",
    "biv": "Bivalenz",
    "hk": "Heizkreis",
    "hzk": "Heizkreis",
    "hk1": "Heizkreis 1",
    "hk2": "Heizkreis 2",
    "hk3": "Heizkreis 3",
    "h1": "Heizkreis 1",
    "h2": "Heizkreis 2",
    "h3": "Heizkreis 3",
    "mi": "Mischer",
    "mia": "Mischer auf",
    "miz": "Mischer zu",
    "mir": "Mischer",
    "m1": "Mischer 1",
    "m2": "Mischer 2",
    "vd": "Verdichter",
    "vd1": "Verdichter 1",
    "vd2": "Verdichter 2",
    "hup": "Heizungsumwälzpumpe",
    "zup": "Zusatzpumpe",
    "wup": "Warmwasserpumpe",
    "zwup": "Zirkulationspumpe",
    "sup": "Schwimmbadpumpe",
    "pup": "Pufferpumpe",
    "pupk": "Pufferpumpe",
    "zwe": "Zweiter Wärmeerzeuger",
    "ven": "Ventilator",
    "vent": "Ventilation",
    "fh": "Flanschheizung",
    "stf": "Störmeldung",
    "raum": "Raum",
    "soll": "Sollwert",
    "ist": "Istwert",
    "temp": "Temperatur",
    "t": "Temperatur",
    "ww": "Warmwasser",
    "vorl": "Vorlauf",
    "rueckl": "Rücklauf",
    "aussen": "Außen",
    "fuehl": "Fühler",
    "zeit": "Zeit",
    "zust": "Zustand",
    "tht": "Thermisches Ventil",
    "ventil": "Ventil",
    "aktiv": "aktiv",
    "frei": "Freigabe",
    "code": "Code",
    "status": "Status",
    "timeprogram": "Zeitprogramm",
    "runtime": "Laufzeit",
    "hour": "Stunde",
    "minute": "Minute",
    "level": "Stufe",
    "flow": "Durchfluss",
    "supply": "Zuluft",
    "exhaust": "Abluft",
    "bypass": "Bypass",
    "zp": "Zeitprogramm",
    "st": "Start",
    "end": "Ende",
    "wmz": "Wärmemengenzähler",
    "zirk": "Zirkulation",
    "wp": "Wärmepumpe",
    "sp": "Speicher",
    "set": "Sollwert",
    "date": "Datum",
    "new": "Neu",
    "mon": "Montag",
    "tue": "Dienstag",
    "wed": "Mittwoch",
    "thu": "Donnerstag",
    "fri": "Freitag",
    "sat": "Samstag",
    "sun": "Sonntag",
}

_ABBREV_EN: dict[str, str] = {
    "a": "Output",
    "e": "Input",
    "p": "Parameter",
    "bs": "Operating hours",
    "ba": "Operation mode",
    "anz": "Display",
    "biv": "Bivalence",
    "hk": "Heating circuit",
    "hzk": "Heating circuit",
    "hk1": "Heating circuit 1",
    "hk2": "Heating circuit 2",
    "hk3": "Heating circuit 3",
    "h1": "Heating circuit 1",
    "h2": "Heating circuit 2",
    "h3": "Heating circuit 3",
    "mi": "Mixer",
    "mia": "Mixer open",
    "miz": "Mixer close",
    "mir": "Mixer",
    "m1": "Mixer 1",
    "m2": "Mixer 2",
    "vd": "Compressor",
    "vd1": "Compressor 1",
    "vd2": "Compressor 2",
    "hup": "Heating circulation pump",
    "zup": "Auxiliary pump",
    "wup": "DHW pump",
    "zwup": "Circulation pump",
    "sup": "Pool pump",
    "pup": "Buffer pump",
    "pupk": "Buffer pump",
    "zwe": "Second heat generator",
    "ven": "Fan",
    "vent": "Ventilation",
    "fh": "Flange heater",
    "stf": "Fault message",
    "raum": "Room",
    "soll": "Setpoint",
    "ist": "Actual",
    "temp": "Temperature",
    "t": "Temperature",
    "ww": "DHW",
    "vorl": "Flow",
    "rueckl": "Return",
    "aussen": "Outdoor",
    "fuehl": "Sensor",
    "zeit": "Time",
    "zust": "State",
    "tht": "Thermal valve",
    "ventil": "Valve",
    "aktiv": "active",
    "frei": "Enable",
    "code": "Code",
    "status": "Status",
    "timeprogram": "Time program",
    "runtime": "Runtime",
    "hour": "Hour",
    "minute": "Minute",
    "level": "Level",
    "flow": "Flow",
    "supply": "Supply air",
    "exhaust": "Exhaust air",
    "bypass": "Bypass",
    "zp": "Time program",
    "st": "Start",
    "end": "End",
    "wmz": "Heat meter",
    "zirk": "Circulation",
    "wp": "Heat pump",
    "sp": "Storage",
    "set": "Setpoint",
    "date": "Date",
    "new": "New",
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def _humanize_key(key: str, abbrev: dict[str, str]) -> str:
    """Erzeugt einen lesbaren Namen aus einem Key über Abkürzungs-Expansion.

    Bekannte Tokens werden ausgeschrieben, reine Zahlen beibehalten, unbekannte
    Tokens in Title-Case übernommen. Fallback, wenn keine i18n-Quelle existiert.
    """
    parts: list[str] = []
    for token in re.split(r"[_]+", key):
        if not token:
            continue
        low = token.lower()
        if low in abbrev:
            parts.append(abbrev[low])
        elif token.isdigit():
            parts.append(token)
        elif token.isupper() or token.islower():
            parts.append(token.capitalize())
        else:
            parts.append(token)
    text = _WS.sub(" ", " ".join(parts)).strip()
    # Aufeinanderfolgende doppelte Wörter zusammenfassen (z. B. "Ventil Ventil").
    words = text.split(" ")
    deduped: list[str] = []
    for word in words:
        if not deduped or deduped[-1].lower() != word.lower():
            deduped.append(word)
    return " ".join(deduped) or key


def _clean(value: str) -> str:
    text = _SHY_ENTITY.sub("", value)
    text = text.replace("\u00ad", "")  # echtes Soft-Hyphen-Zeichen
    text = _HTML_TAG.sub("", text)
    text = _WS.sub(" ", text)
    return text.strip()


def _load_json(path: Path) -> dict:
    if not path.is_file():
        print(f"  WARN: Datei fehlt: {path}")
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _build_name_map(common: dict, easyon: dict) -> dict[str, str]:
    """Merged Klartextnamen. easyon (Parameter-Labels) überschreibt common."""
    merged: dict[str, str] = {}
    for source in (common, easyon):
        for key, value in source.items():
            if not isinstance(value, str):
                continue
            cleaned = _clean(value)
            if cleaned:
                merged[key] = cleaned
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--uhi-root",
        default="../uhi",
        help="Pfad zum UHI-Quellverzeichnis (Default: ../uhi)",
    )
    args = parser.parse_args()

    uhi_root = Path(args.uhi_root).resolve()
    out_dir = (
        Path(__file__).resolve().parent.parent
        / "ha-integration"
        / "custom_components"
        / "dimplex_uhi"
        / "data"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    i18n = uhi_root / "config" / "i18n"
    de_common = _load_json(i18n / "de" / "de.common.json")
    de_easyon = _load_json(i18n / "de" / "de.easyon.json")
    en_common = _load_json(i18n / "en-us" / "en-us.common.json")
    en_easyon = _load_json(i18n / "en-us" / "en-us.easyon.json")

    names_de = _build_name_map(de_common, de_easyon)
    names_en = _build_name_map(en_common, en_easyon)

    device_keys = _load_json(
        uhi_root / "external" / "communicator" / "config" / "deviceKeys.json"
    )

    # Fallback: jeden Device-Key ohne i18n-Namen aus dem Kontext humanisieren,
    # damit in der HA-Oberflaeche kein roher Schluessel angezeigt wird.
    filled_de = filled_en = 0
    for key, meta in device_keys.items():
        if not isinstance(meta, dict):
            continue
        if key not in names_de:
            names_de[key] = _humanize_key(key, _ABBREV_DE)
            filled_de += 1
        if key not in names_en:
            names_en[key] = _humanize_key(key, _ABBREV_EN)
            filled_en += 1

    (out_dir / "names_de.json").write_text(
        json.dumps(names_de, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "names_en.json").write_text(
        json.dumps(names_en, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )
    print(f"  names_de.json: {len(names_de)} Einträge (+{filled_de} Fallback)")
    print(f"  names_en.json: {len(names_en)} Einträge (+{filled_en} Fallback)")

    # Nur die für die Integration relevanten Felder behalten (kompaktere Datei).
    slim: dict[str, dict] = {}
    for key, meta in device_keys.items():
        if not isinstance(meta, dict):
            continue
        slim[key] = {
            "regType": meta.get("regType"),
            "intFac": meta.get("intFac"),
            "minVal": meta.get("minVal"),
            "maxVal": meta.get("maxVal"),
            "unit": meta.get("unit"),
            "desc": meta.get("desc"),
            "monitor": meta.get("monitor"),
        }
    (out_dir / "device_keys.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )
    print(f"  device_keys.json: {len(slim)} Einträge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
