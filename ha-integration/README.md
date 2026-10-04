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
  - Operating mode (`BA_aktiv`) and automatic mode switching (`P_TBaUs`)
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
   integration and enter the host (the port is optional, e.g. `8080`) and the
   language. Token and device ID are not evaluated by the local UHI API and
   can stay empty; they are only passed on as headers (e.g. for a proxy).

## Manual installation

Copy the `custom_components/dimplex_uhi` folder into the
`config/custom_components` directory of Home Assistant and restart Home
Assistant.

## Options

Use *Configure* to adjust the language, the polling intervals for operating
data and version, and the duration used when party mode is selected (the UHI
requires an end time for it).

## Connecting to UHI

The UHI firewall blocks the API port on the network. If Home Assistant cannot
reach the UHI host directly, use one of the options described in the
[repository README](../README.md#reaching-uhi-through-its-firewall) – an SSH
tunnel (no UHI change) or a targeted firewall allow-rule. When tunnelling, enter
the local/forwarded address (e.g. `localhost:8080` or `uhi-tunnel:8080`) as the
integration host.

## Notes

- Some writable parameters (Easyon/commissioning values such as `P_EVS`,
  `P_HK1_*`, `P_EVSGT`) have no UHI read endpoint; the UHI only pushes them via
  Socket.IO when they change. After a restart these entities show the last
  value known to Home Assistant until the UHI reports a new one. A value that
  was never set or reported stays unknown, and a change made directly on the
  heat pump while Home Assistant was offline is only picked up on its next
  change.
- The UHI only pushes changes it detects on the heat pump manager (WPM).
  Changes made through the UHI itself (touch display, UHI app) are not pushed,
  except for the operation mode, so Home Assistant does not see them.
- The UHI does not validate written values against min/max; the limits of the
  number entities are the only safeguard.
- Changing the operation mode keeps the current automatic setting. Party mode
  ends after the configured duration; the end time is sent in Home Assistant's
  local time, so the UHI should use the same time zone.
- If the Socket.IO connection cannot be established at startup, it is retried
  on every poll. After every (re)connect a refresh is triggered.
- Every API request runs a script on the UHI and is re-broadcast to all its
  socket clients, so keep the poll interval moderate. While the socket is
  connected, the operation mode is only polled at the version interval.
- UHI 3.x does not report a MAC address; the serial number of the heat pump
  manager is used as the unique id instead.
- Values are already delivered display-ready (scaled) by the UHI.
- The energy meter is an approximation based on the reported power value, not a
  calibrated meter. It is suitable for trends and the Energy dashboard, but not
  for billing-grade measurements.

## Tests

```bash
pip install -r requirements_test.txt
pytest
```

Run from this directory (`ha-integration/`).

## Data source

The name and metadata files under `custom_components/dimplex_uhi/data/` are
generated from the UHI sources with `tools/extract_names.py`. Run it from the
repository root (`dimplex-ha-system-m/`):

```bash
python3 tools/extract_names.py --uhi-root ../uhi
```
