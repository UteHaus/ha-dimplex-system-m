# Dimplex System M (UHI) – Home Assistant Integration

Native Home Assistant custom component for a **Dimplex System M** heat pump that
is connected through the **UHI** controller software. The integration only talks
to existing UHI endpoints (REST + Socket.IO) – no changes are made to the UHI
itself.

> Part of the [Dimplex System M (UHI) ↔ Home Assistant](../README.md) repo.

## Features

- **Live operating data** via Socket.IO (push) with a periodic REST snapshot.
- **Readable entity names** (DE/EN) from the UHI i18n data, selectable per device.
- **Writable parameters**:
  - Operating mode (`BA_aktiv`)
  - Power/electricity source `P_EVS` (power stage 3 / permanent / limit-temperature dependent)
  - Domestic hot water setpoints, heating curve and utility (EVU) parameters
- **Units and device classes** are assigned automatically (temperature, pressure,
  power, voltage, energy, etc.), including correct icons and long-term statistics.
- **Energy meter**: a derived `Power consumption` sensor integrates the AC power
  input over time (kWh) and can be used in the Home Assistant Energy dashboard.
- Automatic detection of new operating-data keys at runtime.
- Curated core entities are enabled by default; the long tail is added as
  disabled diagnostic entities and can be turned on when needed.

## Installation (HACS)

1. Add the repository as a custom HACS repository (type: Integration).
2. Install "Dimplex System M (UHI)".
3. Restart Home Assistant.
4. Go to *Settings → Devices & Services → Add Integration*, select the
   integration and enter the host (the port is optional, e.g. `8080`), an
   optional token/device ID and the language.

## Manual installation

Copy the `custom_components/dimplex_uhi` folder into the
`config/custom_components` directory of Home Assistant and restart Home
Assistant.

## Options

Use *Configure* to adjust the language as well as the polling intervals for
operating data and version.

## Connecting to UHI

The UHI firewall blocks the API port on the network. If Home Assistant cannot
reach the UHI host directly, use one of the options described in the
[repository README](../README.md#reaching-uhi-through-its-firewall) – an SSH
tunnel (no UHI change) or a targeted firewall allow-rule. When tunnelling, enter
the local/forwarded address (e.g. `localhost:8080` or `uhi-tunnel:8080`) as the
integration host.

## Notes

- Some writable parameters (Easyon/commissioning values such as `P_EVS`,
  `P_HK1_*`, `P_EVSGT`) have no UHI read endpoint. These entities work
  optimistically: the value is applied after setting, but is initially unknown
  after a restart.
- Values are already delivered display-ready (scaled) by the UHI.
- The energy meter is an approximation based on the polled power value, not a
  calibrated meter. It is suitable for trends and the Energy dashboard, but not
  for billing-grade measurements.

## Data source

The name and metadata files under `custom_components/dimplex_uhi/data/` are
generated from the UHI sources with `tools/extract_names.py`. Run it from the
repository root (`dimplex-ha-system-m/`):

```bash
python3 tools/extract_names.py --uhi-root ../uhi
```
