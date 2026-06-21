"""Curated entity definitions for the test setup.

Each entity references a UHI "key" (see external/communicator/config/deviceKeys.json).

read_source:
  - "socket" -> value comes from the live broadcast
                'uhi.collector.operationdata.change-bundle'
  - "rest"   -> value is polled via REST (e.g. operationmode)

write_via:
  - None            -> read-only sensor
  - "operationmode" -> PUT /api/operationmode { id }
  - "functiondata"  -> PUT /api/functiondata/key/:key { value }

scale: factor by which the raw socket value is divided (intFac). Default 1
  (passthrough), since the broadcast usually already provides the
  display-ready value. If values are off by the intFac factor, set scale to
  the intFac from deviceKeys.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Entity:
    id: str
    key: str
    type: str  # "sensor" | "number" | "select"
    read_source: str  # "socket" | "rest"
    name: str
    write_via: str | None = None
    device_class: str | None = None
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    scale: float = 1.0


ENTITIES: list[Entity] = [
    # --- Reading (sensors) ---
    Entity(
        id="aussentemperatur",
        key="E_Aussen_T",
        type="sensor",
        read_source="socket",
        name="Außentemperatur",
        device_class="temperature",
        unit="°C",
    ),
    Entity(
        id="vorlauftemperatur",
        key="E_Vorl_T",
        type="sensor",
        read_source="socket",
        name="Vorlauftemperatur",
        device_class="temperature",
        unit="°C",
    ),
    Entity(
        id="ruecklauftemperatur",
        key="E_Rueckl_T",
        type="sensor",
        read_source="socket",
        name="Rücklauftemperatur",
        device_class="temperature",
        unit="°C",
    ),
    Entity(
        id="warmwassertemperatur",
        key="E_Ww_Fuehl",
        type="sensor",
        read_source="socket",
        name="Warmwassertemperatur",
        device_class="temperature",
        unit="°C",
    ),
    # --- Writing ---
    Entity(
        # Operation mode as a selection. Options come from
        # GET /api/operationmode/list, status from GET /api/operationmode.
        id="betriebsmodus",
        key="BA_aktiv",
        type="select",
        read_source="rest",
        write_via="operationmode",
        name="Betriebsmodus",
    ),
    Entity(
        # Domestic hot water setpoint. Write via functiondata, read via socket.
        id="warmwasser_soll",
        key="P_WW_SOLL",
        type="number",
        read_source="socket",
        write_via="functiondata",
        name="Warmwasser-Solltemperatur",
        device_class="temperature",
        unit="°C",
        min=30,
        max=85,
        step=1,
    ),
]
