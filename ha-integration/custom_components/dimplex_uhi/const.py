"""Constants of the Dimplex System M (UHI) integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dimplex_uhi"

# Device/manufacturer metadata
MANUFACTURER: Final = "Dimplex"
MODEL: Final = "System M"
DEFAULT_DEVICE_NAME: Final = "Dimplex System M"

# Config/options keys
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_TOKEN: Final = "token"
CONF_DEVICE_ID: Final = "device_id"
CONF_NAME: Final = "name"
CONF_LANGUAGE: Final = "language"
CONF_VERSION_INTERVAL: Final = "version_interval"
CONF_STATE_INTERVAL: Final = "state_interval"

DEFAULT_PORT: Final = 8080
DEFAULT_LANGUAGE: Final = "de"
SUPPORTED_LANGUAGES: Final = ("de", "en")

# Poll intervals (seconds)
DEFAULT_VERSION_INTERVAL: Final = 300
DEFAULT_STATE_INTERVAL: Final = 60

# Socket.IO
SOCKETIO_PATH: Final = "/broadcast/socket"
OPERATIONDATA_EVENT: Final = "uhi.collector.operationdata.change-bundle"

# All known operating-data groups for the snapshot via
# GET /api/functiondata/groups.
SNAPSHOT_GROUPS: Final = (
    "GROUP_01",
    "FUNKTIONSHEIZEN",
    "BELEGREIFHEIZEN",
    "FUNKTIONSKONTROLLE_PUMPE",
    "FUNKTIONSKONTROLLE_HEIZSTAB",
    "FUNKTIONSKONTROLLE_MISCHER_VENTILE",
    "TAKTUNGEN",
    "LAUFZEITEN",
    "MISC",
    "FUNKTIONS_SPERRE",
    "VENTILATION",
    "WAERMEMENGEN",
    "DATEN_DISPLAY_BETREIBER",
    "OUTPUTS",
    "INPUTS",
)

# Unit mapping UHI (physicalUnit string) -> Home Assistant
UNIT_MAP: Final = {
    "UNIT_DEG_C": "°C",
    "UNIT_DEG_KELVIN": "K",
    "Grad C": "°C",
    "Grad Celsius": "°C",
    "Grad K": "K",
    "K": "K",
    "Prozent": "%",
    "Sekunden": "s",
    "Minuten": "min",
    "Stunden": "h",
    "U/min": "rpm",
    "bar": "bar",
    "l/h": "L/h",
    "NO_UNIT": None,
    "": None,
    None: None,
}
