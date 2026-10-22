# Notes for agents and contributors

## Layout
- `custom_components/dimplex_uhi/` – HA integration (HACS needs it in the repo root, with `hacs.json`).
- `ha-bridge/` – optional MQTT bridge; `tools/` – tunnel, firewall rule, `extract_names.py`.
- Tests: `pytest` from the root (`requirements_test.txt`); lint: `uvx ruff check .`.
- Release: bump `version` in `manifest.json`, push tag `v<version>` (workflow checks they match).

## UHI facts (verified on UHI 4.3.4, the version on the heat pump)
- **Write bodies must be byte-identical to `JSON.stringify`** (compact, `10` not `10.0`, no ASCII escaping). The UHI re-sends every request internally with the original `Content-Length`; any other JSON makes writes hang and end in HTTP 502 after 60 s. Use `encode_body` (integration and bridge).
- Reading: `/api/functiondata/groups` only covers the groups in `deviceKeyGroups.json`; one unknown group fails the whole request.
- Operator settings come from `/api/heatingunit` (setpoints), `/api/operationmode` (mode, `is_automatic_mode`, limits) and `/api/data/rapidheating`. Omitting `is_automatic_mode` on PUT switches automatic mode off; party mode needs `dateEnd`.
- `GET /api/operationmode` returns `{id, is_automatic_mode, ...}` directly (not wrapped).
- Commissioning (EasyOn) parameters (`P_EVS`, `P_HK1_END`, …) have no read endpoint – only pushed when they change. Keep them read-only.
- Push: Socket.IO `/broadcast/socket`, events `uhi.collector.operationdata.change-bundle` and `api.response` (every API call of any client, incl. touch-display writes; UHI 4.x re-runs groups/operationmode on change). Writes through the UHI are not part of change bundles.
- `SmartGrid_*` flags are WPM inputs: writes are accepted but overwritten within ~1 min. SG control = relays on the SG Ready terminals.
- No MAC in `/api/system/version` on UHI 3.x – serial number is the fallback unique id.
- The local device API has no authentication; the firewall is the only protection.

## Home Assistant pitfalls
- HA 2026.10 prefixes new entity ids with the area; `entity_id_adder` suggests ids without it, `migrate.py` fixes old ones.
- Changing an entity's platform (number → sensor) creates a new entity; migrate the registry instead of leaving orphans.

## Working on the real device
- Ask the user before any write to the heat pump. Safe test: write the current value back, or a time-boxed change with automatic restore while watching `Stoerung_Wert`/`Fehler_Wert`.
- UHI sources: installed copy is identical to `../uhi_ho/uhi_source` (4.3.4); `~/Dokumente/dimplex/dimplex uhi` is an older 3.1.4.
