# UHI → Home Assistant Bridge (test setup)

A simple, decoupled test setup to display/historize data from the UHI heat pump
in **Home Assistant** and to set values – **without any changes to UHI**. The
bridge only uses existing UHI interfaces (REST + Socket.IO).

> Part of the [Dimplex System M (UHI) ↔ Home Assistant](../README.md) repo.
> For the recommended native integration and for the firewall/tunnel options,
> see the [repository README](../README.md).

## Architecture

```
UHI (heat pump controller)                 Home Assistant
  ├─ Socket.IO /broadcast/socket  ─┐         ▲
  │   (live operating data)        │         │ MQTT Discovery + State
  └─ REST /api/...                 ▼         │
       (version, mode, writes)   ┌─────────────────┐
                                 │   ha-bridge     │──► Mosquitto ──► HA
        ◄── PUT (set) ───────────│  (Python, uv)   │◄── Commands ◄── HA
                                 └─────────────────┘
```

- **Reading:** live values arrive via the Socket.IO event
  `uhi.collector.operationdata.change-bundle`. Version/operating mode are
  additionally polled periodically via REST (the socket only sends on changes).
- **Writing:** HA commands are mapped to `PUT /api/operationmode` or
  `PUT /api/functiondata/key/:key`.
- **Version:** `GET /api/system/version` returns UHI and firmware versions
  → HA device `sw_version` + diagnostic sensors.
- **History:** handled automatically by Home Assistant.

## Requirements

- Docker + Docker Compose **or** Python ≥ 3.11 with [uv](https://docs.astral.sh/uv/)
- Network access to the UHI API. Because the UHI firewall blocks the API port,
  the compose stack includes an **SSH tunnel container** (`uhi-tunnel`) that
  forwards it. See [Reaching UHI through its firewall](../README.md#reaching-uhi-through-its-firewall).

## Quick start with Docker

One-time SSH key setup for the tunnel container (it cannot type a password):

```bash
cd ha-bridge
ssh-keygen -t ed25519 -N '' -f ../tools/tunnel/keys/id_uhi
ssh-copy-id -i ../tools/tunnel/keys/id_uhi.pub pi@<UHI_IP>   # one-time password
```

Then start the stack:

```bash
docker compose up --build -d
```

- Home Assistant: <http://localhost:8123>
- MQTT broker (Mosquitto): `localhost:1883`

In Home Assistant, add the **MQTT integration**
(*Settings → Devices & Services → Add Integration → MQTT*), broker host
`mosquitto`, port `1883`. The device **"UHI heat pump"** then appears
automatically with sensors, operating-mode selection, domestic hot water
setpoint and version diagnostic sensors.

> Note: inside the stack the bridge reaches UHI via the tunnel container at
> `http://uhi-tunnel:8080`. Set the device address in the `uhi-tunnel` service
> (`SSH_HOST`) in `docker-compose.yml`. If you forward the API another way,
> adjust `UHI_BASE_URL`/`UHI_SOCKET_URL` on the `bridge` service instead.

## Local without Docker (bridge only)

Prerequisite: an MQTT broker and UHI are already running.

```bash
cd ha-bridge/bridge
cp .env.example .env        # adjust values
uv sync                     # install dependencies
uv run python -m uhi_ha_bridge
```

## Configuration (environment variables)

| Variable                   | Default                   | Meaning                                       |
| -------------------------- | ------------------------- | --------------------------------------------- |
| `MQTT_URL`                 | `mqtt://localhost:1883`   | MQTT broker                                   |
| `MQTT_USERNAME`/`_PASSWORD`| –                         | optional MQTT auth                            |
| `UHI_BASE_URL`             | `http://localhost:8080`   | UHI REST base                                 |
| `UHI_SOCKET_URL`           | = `UHI_BASE_URL`          | UHI Socket.IO base                            |
| `UHI_BEARER_TOKEN`         | –                         | optional, if the UHI API requires auth        |
| `UHI_DEVICE_ID`            | –                         | optional, `Device` header                     |
| `INITIAL_SNAPSHOT`         | `true`                    | fetch all values once via REST on startup     |
| `SNAPSHOT_GROUPS`          | all 15 groups             | comma-separated list of groups to query       |
| `HA_DISCOVERY_PREFIX`      | `homeassistant`           | HA MQTT discovery prefix                      |
| `NODE_ID`                  | `uhi`                     | topic/ID base of this instance                |
| `VERSION_POLL_INTERVAL_MS` | `60000`                   | polling interval for version                  |
| `STATE_POLL_INTERVAL_MS`   | `15000`                   | polling interval for operating mode           |
| `DEVICE_KEYS_PATH`         | –                         | optional path to `deviceKeys.json`            |
| `LOG_LEVEL`                | `info`                    | `error`/`warn`/`info`/`debug`                 |

## Customizing entities

The monitored/controllable values are defined in
[`bridge/uhi_ha_bridge/entities.py`](bridge/uhi_ha_bridge/entities.py).
Deliberately kept small for testing:

| Entity                   | UHI key       | Type   | Direction |
| ------------------------ | ------------- | ------ | --------- |
| Outdoor temperature      | `E_Aussen_T`  | sensor | read      |
| Flow temperature         | `E_Vorl_T`    | sensor | read      |
| Return temperature       | `E_Rueckl_T`  | sensor | read      |
| Domestic hot water temp. | `E_Ww_Fuehl`  | sensor | read      |
| Operating mode           | `BA_aktiv`    | select | write     |
| DHW setpoint             | `P_WW_SOLL`   | number | write     |

## Tests / debugging

Watch MQTT:

```bash
mosquitto_sub -h localhost -t 'homeassistant/#' -t 'uhi/#' -v
```

Expectation:
1. On startup: discovery configs under `homeassistant/.../config` and state
   topics under `uhi/uhi/<entity>/state`.
2. Change a UHI value → the matching state updates; history in HA fills up.
3. Switch the operating mode in HA → the log shows `PUT /api/operationmode`.

## Notes / limits

- The socket only sends on changes. So that HA sees values immediately, the
  bridge fetches all values once via REST on startup
  (`GET /api/functiondata/groups`, controlled via `INITIAL_SNAPSHOT`). Version
  and operating mode are additionally polled periodically.
- This is a **test setup**. For a production implementation the bridge can later
  be moved into a native UHI module.
