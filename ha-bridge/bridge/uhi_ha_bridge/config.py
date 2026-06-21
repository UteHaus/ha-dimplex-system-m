"""Configuration from environment variables (optionally via .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, fallback: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def _str(name: str, fallback: str | None) -> str | None:
    raw = os.environ.get(name)
    return fallback if raw is None or raw == "" else raw


def _csv(name: str, fallback: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return fallback
    return [item.strip() for item in raw.split(",") if item.strip()]


def _bool(name: str, fallback: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    return raw.strip().lower() in ("1", "true", "yes", "on")


# All known operating-data groups (deviceKeyGroups.json) for the
# initial snapshot via GET /api/functiondata/groups.
DEFAULT_SNAPSHOT_GROUPS = [
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
]


@dataclass(frozen=True)
class MqttConfig:
    enabled: bool
    url: str
    username: str | None
    password: str | None


@dataclass(frozen=True)
class UhiConfig:
    base_url: str
    socket_url: str
    bearer_token: str | None
    device_id: str | None
    initial_snapshot: bool
    snapshot_groups: list[str]


@dataclass(frozen=True)
class HaConfig:
    discovery_prefix: str
    node_id: str


@dataclass(frozen=True)
class Intervals:
    version_poll_s: float
    state_poll_s: float


@dataclass(frozen=True)
class Config:
    mqtt: MqttConfig
    uhi: UhiConfig
    ha: HaConfig
    intervals: Intervals
    log_level: str
    device_keys_path: str | None
    unknown_log_path: str | None


def load_config() -> Config:
    base_url = _str("UHI_BASE_URL", "http://localhost:8080")
    return Config(
        mqtt=MqttConfig(
            enabled=_bool("MQTT_ENABLED", True),
            url=_str("MQTT_URL", "mqtt://localhost:1883"),
            username=_str("MQTT_USERNAME", None),
            password=_str("MQTT_PASSWORD", None),
        ),
        uhi=UhiConfig(
            base_url=base_url,
            socket_url=_str("UHI_SOCKET_URL", base_url),
            bearer_token=_str("UHI_BEARER_TOKEN", None),
            device_id=_str("UHI_DEVICE_ID", None),
            initial_snapshot=_bool("INITIAL_SNAPSHOT", True),
            snapshot_groups=_csv("SNAPSHOT_GROUPS", DEFAULT_SNAPSHOT_GROUPS),
        ),
        ha=HaConfig(
            discovery_prefix=_str("HA_DISCOVERY_PREFIX", "homeassistant"),
            node_id=_str("NODE_ID", "uhi"),
        ),
        intervals=Intervals(
            version_poll_s=_int("VERSION_POLL_INTERVAL_MS", 60000) / 1000.0,
            state_poll_s=_int("STATE_POLL_INTERVAL_MS", 15000) / 1000.0,
        ),
        log_level=_str("LOG_LEVEL", "info"),
        device_keys_path=_str("DEVICE_KEYS_PATH", None),
        unknown_log_path=_str("UNKNOWN_LOG_PATH", "unknown_entities.log"),
    )
