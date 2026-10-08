"""Client for UHI.

Uses only existing endpoints/socket - NO changes are made to UHI.

- REST (requests): read version, read/set operation mode, set function data
- Socket.IO (python-socketio < 5, compatible with UHI socket.io server v2):
  live operating data via event 'uhi.collector.operationdata.change-bundle'
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging

import requests
import socketio

from .config import Config

logger = logging.getLogger("uhi-ha-bridge.uhi")


def _js_value(value):
    """Integral floats as int, like JavaScript prints them (10.0 -> 10)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _js_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_js_value(v) for v in value]
    return value


def encode_body(payload: dict) -> bytes:
    """Serialize a request body exactly like JSON.stringify.

    The UHI re-sends every API request internally with the original
    Content-Length but a body re-serialized by JSON.stringify. If the lengths
    differ (Python adds spaces after ':' and ','), the internal request waits
    for missing bytes and the UHI answers HTTP 502 after 60 s.
    """
    return json.dumps(
        _js_value(payload), separators=(",", ":"), ensure_ascii=False
    ).encode()


class UhiClient:
    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._session = requests.Session()
        headers = {}
        if config.uhi.bearer_token:
            headers["Authorization"] = f"Bearer {config.uhi.bearer_token}"
        if config.uhi.device_id:
            headers["Device"] = config.uhi.device_id
        self._session.headers.update(headers)

        self._sio = socketio.Client(
            reconnection=True,
            reconnection_delay=2,
            logger=False,
            engineio_logger=False,
        )
        self._on_operationdata: Callable[[dict], None] | None = None
        self._register_socket_handlers()

    # ---------------- Socket.IO ----------------
    def on_operationdata(self, handler: Callable[[dict], None]) -> None:
        self._on_operationdata = handler

    def _register_socket_handlers(self) -> None:
        @self._sio.event
        def connect() -> None:
            logger.info("Socket.IO connected")

        @self._sio.event
        def disconnect() -> None:
            logger.warning("Socket.IO disconnected")

        @self._sio.on("uhi.collector.operationdata.change-bundle")
        def _on_bundle(data) -> None:
            # Payload structure: { event, payload: { KEY: value, ... }, _meta }
            values = data.get("payload") if isinstance(data, dict) else None
            if not isinstance(values, dict):
                return
            logger.debug("operationdata bundle: %s", values)
            if self._on_operationdata:
                self._on_operationdata(values)

    def connect_socket(self) -> None:
        url = self._cfg.uhi.socket_url
        logger.info("Connecting Socket.IO to %s (path /broadcast/socket)", url)
        try:
            self._sio.connect(
                url,
                socketio_path="/broadcast/socket",
                transports=["websocket", "polling"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Socket.IO connection failed: %s", exc)

    # ---------------- REST ----------------
    def _url(self, path: str) -> str:
        return f"{self._cfg.uhi.base_url}{path}"

    def get_version(self) -> dict:
        resp = self._session.get(self._url("/api/system/version"), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_operation_mode_list(self) -> list[dict]:
        resp = self._session.get(self._url("/api/operationmode/list"), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    def get_operation_mode(self) -> dict:
        resp = self._session.get(self._url("/api/operationmode"), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, payload: dict) -> dict:
        resp = self._session.put(
            self._url(path),
            data=encode_body(payload),
            headers={"Content-Type": "application/json"},
            # Writes run a script on the UHI; its proxy gives up after 60 s.
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def set_operation_mode(self, mode_id: int) -> dict:
        return self._put("/api/operationmode", {"id": mode_id})

    def set_function_data(self, key: str, value) -> dict:
        return self._put(f"/api/functiondata/key/{key}", {"value": value})

    def get_function_data_groups(self, groups: list[str]) -> dict:
        """Read the current values of multiple groups at once.

        GET /api/functiondata/groups?groups=GROUP_01,FUNKTIONSHEIZEN,...
        Response: { GROUP: [ { key, value, definition }, ... ], ... }
        """
        resp = self._session.get(
            self._url("/api/functiondata/groups"),
            params={"groups": ",".join(groups)},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def close(self) -> None:
        try:
            if self._sio.connected:
                self._sio.disconnect()
        except Exception:  # noqa: BLE001
            pass
