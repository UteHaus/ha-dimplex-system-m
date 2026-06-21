"""Static models: writable keys, curated list, typing logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import UNIT_MAP

# Platform identifiers (match the HA platform files)
PLATFORM_SENSOR = "sensor"
PLATFORM_BINARY_SENSOR = "binary_sensor"
PLATFORM_NUMBER = "number"
PLATFORM_SELECT = "select"


@dataclass(frozen=True)
class WritableSpec:
    """Definition of a writable entity."""

    key: str
    platform: str  # "number" | "select"
    write_via: str  # "functiondata" | "operationmode"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None
    device_class: str | None = None
    # For select with a fixed value list: raw values (as str) in order.
    option_values: tuple[str, ...] = field(default_factory=tuple)


# Extended, confirmed write list.
WRITABLE_SPECS: dict[str, WritableSpec] = {
    "BA_aktiv": WritableSpec(
        key="BA_aktiv",
        platform=PLATFORM_SELECT,
        write_via="operationmode",
    ),
    "P_EVS": WritableSpec(
        key="P_EVS",
        platform=PLATFORM_SELECT,
        write_via="functiondata",
        option_values=("1", "2", "3"),
    ),
    "P_WW_SOLL": WritableSpec(
        key="P_WW_SOLL",
        platform=PLATFORM_NUMBER,
        write_via="functiondata",
        min=30,
        max=85,
        step=1,
        unit="°C",
        device_class="temperature",
    ),
    "P_WW_SOLLAB": WritableSpec(
        key="P_WW_SOLLAB",
        platform=PLATFORM_NUMBER,
        write_via="functiondata",
        min=30,
        max=85,
        step=1,
        unit="°C",
        device_class="temperature",
    ),
    "P_HK1_WK": WritableSpec(
        key="P_HK1_WK",
        platform=PLATFORM_NUMBER,
        write_via="functiondata",
        min=-19,
        max=38,
        step=1,
    ),
    "P_HK1_END": WritableSpec(
        key="P_HK1_END",
        platform=PLATFORM_NUMBER,
        write_via="functiondata",
        min=20,
        max=70,
        step=1,
        unit="°C",
        device_class="temperature",
    ),
    "P_HK1_MAX": WritableSpec(
        key="P_HK1_MAX",
        platform=PLATFORM_NUMBER,
        write_via="functiondata",
        min=25,
        max=70,
        step=1,
        unit="°C",
        device_class="temperature",
    ),
    "P_HK1_FWR_SOLL": WritableSpec(
        key="P_HK1_FWR_SOLL",
        platform=PLATFORM_NUMBER,
        write_via="functiondata",
        min=0,
        max=60,
        step=1,
        unit="°C",
        device_class="temperature",
    ),
    "P_HK1_RT_GT": WritableSpec(
        key="P_HK1_RT_GT",
        platform=PLATFORM_NUMBER,
        write_via="functiondata",
        min=15,
        max=30,
        step=1,
        unit="°C",
        device_class="temperature",
    ),
    "P_EVSGT": WritableSpec(
        key="P_EVSGT",
        platform=PLATFORM_NUMBER,
        write_via="functiondata",
        min=-10,
        max=10,
        step=1,
        unit="°C",
        device_class="temperature",
    ),
}

# Core sensors that are enabled by default (in addition to the group
# DATEN_DISPLAY_BETREIBER and all writable keys).
CURATED_SENSOR_KEYS: frozenset[str] = frozenset(
    {
        "E_Aussen_T",
        "E_Vorl_T",
        "E_Rueckl_T",
        "E_Ww_Fuehl",
        "WPIO2_r_ECT_AC_Inp_Power",
        "WPIO2_r_ECT_AC_Inp_Volt",
        "WPIO2_r_ECT_Comp_Hz",
    }
)

# Groups whose keys are visible by default (operator display).
CURATED_GROUPS: frozenset[str] = frozenset({"DATEN_DISPLAY_BETREIBER"})


def resolve_unit(definition: dict | None, meta: dict | None) -> str | None:
    """Resolve the HA unit from definition (physicalUnit) or deviceKeys."""
    if definition:
        phys = definition.get("physicalUnit")
        if phys in UNIT_MAP:
            return UNIT_MAP[phys]
        if phys:
            return phys or None
    if meta:
        return UNIT_MAP.get(meta.get("unit"))
    return None


# Unit overrides for keys whose UHI physicalUnit is missing (NO_UNIT)
# but whose quantity is known (inverter telemetry).
KEY_UNIT_OVERRIDES: dict[str, str] = {
    "WPIO2_r_ECT_AC_Inp_Power": "W",
    "WPIO2_r_ECT_AC_Inp_Volt": "V",
    "WPIO2_r_ECT_Comp_Hz": "Hz",
}

# Key of the electrical power input (basis of the energy calculation).
ENERGY_POWER_KEY = "WPIO2_r_ECT_AC_Inp_Power"


def resolve_unit_for_key(
    key: str, definition: dict | None, meta: dict | None
) -> str | None:
    """Unit including key-specific overrides."""
    override = KEY_UNIT_OVERRIDES.get(key)
    if override is not None:
        return override
    return resolve_unit(definition, meta)


def is_binary(definition: dict | None, meta: dict | None) -> bool:
    """Heuristic: 0/1 value range without unit -> binary_sensor."""
    if meta and meta.get("regType") == "D":
        return True
    lo = hi = None
    if definition:
        lo = definition.get("numberMin")
        hi = definition.get("numberMax")
    if (lo, hi) == (None, None) and meta:
        lo = meta.get("minVal")
        hi = meta.get("maxVal")
    if lo == 0 and hi == 1:
        unit = resolve_unit(definition, meta)
        if not unit:
            return True
    return False


def classify_platform(key: str, definition: dict | None, meta: dict | None) -> str:
    """Determine the HA platform for a key."""
    spec = WRITABLE_SPECS.get(key)
    if spec is not None:
        return spec.platform
    if is_binary(definition, meta):
        return PLATFORM_BINARY_SENSOR
    return PLATFORM_SENSOR


def is_curated(key: str, group: str | None) -> bool:
    """True if the entity should be enabled by default."""
    if key in WRITABLE_SPECS:
        return True
    if key in CURATED_SENSOR_KEYS:
        return True
    if group is not None and group in CURATED_GROUPS:
        return True
    return False


def coerce_number(payload: Any) -> Any:
    """Convert a write value to int/float if possible."""
    try:
        value = float(payload)
    except (TypeError, ValueError):
        return payload
    return int(value) if value.is_integer() else value


# HA unit -> (device_class, state_class) for measurement sensors.
_UNIT_CLASSES: dict[str, tuple[str | None, str]] = {
    "°C": ("temperature", "measurement"),
    "K": ("temperature", "measurement"),
    "%": (None, "measurement"),
    "s": ("duration", "measurement"),
    "min": ("duration", "measurement"),
    "h": ("duration", "measurement"),
    "rpm": (None, "measurement"),
    "bar": ("pressure", "measurement"),
    "L/h": ("volume_flow_rate", "measurement"),
    "W": ("power", "measurement"),
    "V": ("voltage", "measurement"),
    "A": ("current", "measurement"),
    "Hz": ("frequency", "measurement"),
    "kWh": ("energy", "total_increasing"),
}


def resolve_sensor_classes(unit: str | None) -> tuple[str | None, str | None]:
    """(device_class, state_class) matching the HA unit."""
    return _UNIT_CLASSES.get(unit, (None, None))


# device_class for binary sensors (0/1) based on the key
# (order = priority).
_BINARY_DC_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "hup", "zup", "wup", "sup", "pup", "zwup", "ven", "vent",
            "vd", "verdichter", "drhz", "kessel",
        ),
        "running",
    ),
    (("stf", "stoer", "fault", "ndp", "hdp", "pressost"), "problem"),
    (("sperre", "block"), "lock"),
    (("mia", "miz", "_mi", "ventil"), "opening"),
)


def resolve_binary_device_class(key: str) -> str | None:
    """BinarySensor device_class or None."""
    low = key.lower()
    for needles, dc in _BINARY_DC_RULES:
        if any(needle in low for needle in needles):
            return dc
    return None
