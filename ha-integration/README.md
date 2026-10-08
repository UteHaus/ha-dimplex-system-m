# Dimplex System M (UHI) – Home Assistant Integration

Native Home Assistant custom component for a **Dimplex System M** heat pump that
is connected through the **UHI** controller software. The integration only talks
to existing UHI endpoints (REST + Socket.IO) – no changes are made to the UHI
itself.

> Part of the [Dimplex System M (UHI) ↔ Home Assistant](../README.md) repo.

## Features

- **Live operating data** via Socket.IO (push) with a periodic REST snapshot.
- **Readable entity names** (DE/EN) from the UHI i18n data, selectable per device.
- **Adjustable settings** – exactly what the UHI user interface offers an
  operator, with the limits the UHI reports:
  - Operating mode and automatic mode switching, including its heating and
    cooling limit and switching delay
  - Setpoint of each heating unit: heating curve shift (or flow/room setpoint,
    depending on the circuit type), hot water, and the pool if it delivers a
    reading
  - Rapid heating level of the heating circuits
  - Hot water minimum temperature (`P_WW_MIN_TEMP`)
- **Commissioning parameters** (EVU lock `P_EVS`, `P_EVSGT`, heating curve end
  point, max. return temperature, fixed setpoint, room control limit, hot water
  max. temperature) are shown read-only; they are set via the EasyOn wizard of
  the UHI.
- **Smart Grid** state (low / normal / high / problem) as reported by the WPM
  (read-only, see [Smart Grid](#smart-grid-sg-ready)).
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

Copy the [`custom_components/dimplex_uhi`](../custom_components/dimplex_uhi/) folder (repository root) into the
`config/custom_components` directory of Home Assistant and restart Home
Assistant.

## Options

Use *Configure* to adjust the language, the poll interval used while the
Socket.IO connection is down, the version poll interval, and the duration used
when party mode is selected (the UHI requires an end time for it).

### Smart Grid (SG Ready)

The integration shows the Smart Grid state the WPM reports. It cannot set it:
the UHI offers no Smart Grid control, and the WPM's Smart Grid flags
(`SmartGrid_Niedrig/Normal/Hoch`) are inputs of the WPM. Tested on UHI 4.3.4:
the UHI accepts a write to these flags, but the WPM overwrites it with its own
state at the next synchronisation (within about a minute).

To control Smart Grid from Home Assistant, use the SG Ready terminals of the
WPM as intended by Dimplex: two potential-free contacts (e.g. relays switched
by Home Assistant) on the WPM's SG Ready inputs, with Smart Grid enabled in the
commissioning (EasyOn) of the WPM. The integration then shows the resulting
state.

## Connecting to UHI

The UHI firewall blocks the API port on the network. If Home Assistant cannot
reach the UHI host directly, use one of the options described in the
[repository README](../README.md#reaching-uhi-through-its-firewall) – an SSH
tunnel (no UHI change) or a targeted firewall allow-rule. When tunnelling, enter
the local/forwarded address (e.g. `localhost:8080` or `uhi-tunnel:8080`) as the
integration host.

## Notes

- The commissioning parameters have no UHI read endpoint; the UHI only
  pushes them via Socket.IO when they change. They stay unknown until then;
  afterwards the last value is restored after a restart.
- Heating units are read once at setup; a unit added later on the WPM appears
  after reloading the integration.
- Live data comes from two Socket.IO events: change bundles for values the UHI
  reads from the heat pump manager (WPM), and the `api.response` broadcasts the
  UHI sends for API calls of any client. The latter also carries writes made
  on the UHI touch display or app, group snapshots and the operation mode
  including the automatic flag (UHI 4.x re-runs these requests whenever one of
  their values changes).
- The UHI does not validate written values against min/max; the limits of the
  number entities are the only safeguard. Limits reported by the UHI take
  precedence over the built-in ones.
- Robustness against UHI updates: if the UHI rejects a snapshot group (e.g.
  renamed or removed), the groups are read one by one and the failing one is
  skipped (logged, retried hourly). If the socket is connected but no change
  bundle arrives for 5 minutes, the regular poll interval applies again.
- Changing the operation mode keeps the current automatic setting. Party mode
  ends after the configured duration; the end time is sent in Home Assistant's
  local time, so the UHI should use the same time zone.
- Every API request runs a script on the UHI, so the REST snapshot (groups and
  operation mode) is only a safety net while the socket is connected: it runs
  every 10 minutes, otherwise at the configured interval. If the socket cannot
  be established, it is retried on every poll; after a reconnect a full
  refresh is triggered.
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

Run from the repository root; the tests live in [`tests/`](../tests/).

## Data source

The name and metadata files under `custom_components/dimplex_uhi/data/` are
generated from the UHI sources with `tools/extract_names.py`. Run it from the
repository root (`dimplex-ha-system-m/`):

```bash
python3 tools/extract_names.py --uhi-root ../uhi
```
