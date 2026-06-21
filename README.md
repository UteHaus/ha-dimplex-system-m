# Dimplex System M (UHI) ↔ Home Assistant

Connect a **Dimplex System M** heat pump (driven by the **UHI** controller
software) to **Home Assistant**. Everything here uses only the *existing* UHI
interfaces (REST + Socket.IO) — **the UHI itself is never modified**.

> Tested with UHI firmware **4.3.4**.

> Unofficial community project. Not affiliated with or endorsed by
> Glen Dimplex. "Dimplex" and "System M" are trademarks of their owners.

## What's in this repo

| Folder | Purpose |
|--------|---------|
| [`ha-integration/`](ha-integration/) | Native Home Assistant custom component `dimplex_uhi` (recommended). |
| [`ha-bridge/`](ha-bridge/) | Optional UHI → MQTT bridge test setup (Docker Compose: Mosquitto + HA + bridge + SSH tunnel). |
| [`tools/`](tools/) | Helper scripts: SSH tunnel, firewall allow-rule, name/metadata generator. |

## Two ways to use it

### 1. Native integration (recommended)

Install the custom component and add it through the HA UI. See
[`ha-integration/README.md`](ha-integration/README.md).

- Install via HACS (custom repository, type *Integration*) **or** copy
  `ha-integration/custom_components/dimplex_uhi` into `config/custom_components`.
- Restart HA → *Settings → Devices & Services → Add Integration → Dimplex
  System M (UHI)* → enter the UHI host/port.

When running HA in Docker, you can mount the component directly instead of
copying it (changes show up after an HA restart):

```yaml
# docker-compose.yml
services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    volumes:
      - ./config:/config
      - ./dimplex-ha-system-m/ha-integration/custom_components/dimplex_uhi:/config/custom_components/dimplex_uhi:ro
```

```bash
# or with plain docker run
docker run -d --name homeassistant \
  -v "$PWD/config:/config" \
  -v "$PWD/dimplex-ha-system-m/ha-integration/custom_components/dimplex_uhi:/config/custom_components/dimplex_uhi:ro" \
  ghcr.io/home-assistant/home-assistant:stable
```

### 2. MQTT bridge (test setup)

A decoupled Docker Compose stack that publishes UHI data to HA via MQTT
discovery. See [`ha-bridge/README.md`](ha-bridge/README.md).

```bash
cd ha-bridge
docker compose up --build -d
```

## Reaching UHI through its firewall

The UHI firewall **blocks the API port (tcp/80)** from the network but allows
SSH (tcp/22) and loopback. Pick **one** of the options below so Home Assistant
can read/write the API. Option A is recommended (no UHI change).

### Option A — SSH tunnel (no UHI change, firewall stays on)

The API is forwarded over SSH to `127.0.0.1:<API_PORT>` on the device, where it
is reachable locally.

**A1 — Docker (part of the bridge stack, persistent).**
Needs SSH **key** auth (a container cannot type a password):

```bash
cd ha-bridge
ssh-keygen -t ed25519 -N '' -f ../tools/tunnel/keys/id_uhi
ssh-copy-id -i ../tools/tunnel/keys/id_uhi.pub pi@<UHI_IP>   # one-time password
docker compose up -d --build
docker compose logs -f uhi-tunnel
```

Other services then reach UHI at `http://uhi-tunnel:8080`. The container source
is in [`tools/tunnel/`](tools/tunnel/).

**A2 — Standalone script (no Docker).** Prompts for the connection details and
the local port to use; works with password auth:

```bash
tools/dimplex_uhi_tunnel.sh
# then point HA / the bridge at http://localhost:<LOCAL_PORT>
```

### Option B — Open a targeted firewall rule (patches UHI)

Keeps the firewall enabled but adds an allow rule for the API port from one
source IP/CIDR, and patches the UHI firewall source so it survives a re-lock.
Re-run after a UHI update.

```bash
tools/dimplex_uhi_firewall.sh
```

See [`tools/`](tools/) for both scripts. They are interactive (prompt for
`SSH_USER`/`SSH_HOST`/`SSH_PORT`/`SSH_KEY`).

## Icons / branding

The official Dimplex artwork for the `dimplex_uhi` domain lives in
[`ha-integration/custom_components/dimplex_uhi/brands/`](ha-integration/custom_components/dimplex_uhi/brands/).
Home Assistant only shows it once submitted to the
[home-assistant/brands](https://github.com/home-assistant/brands) repo under
`custom_integrations/dimplex_uhi/`; until then per-entity icons are used.

## Regenerating name/metadata files

Run from the repository root (requires the UHI sources next to the repo):

```bash
python3 tools/extract_names.py --uhi-root ../uhi
```
