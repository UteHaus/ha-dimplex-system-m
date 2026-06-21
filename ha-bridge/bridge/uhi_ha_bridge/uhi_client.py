"""Client for UHI.

Uses only existing endpoints/socket - NO changes are made to UHI.

- REST (requests): read version, read/set operation mode, set function data
- Socket.IO (python-socketio < 5, compatible with UHI socket.io server v2):
  live operating data via event 'uhi.collector.operationdata.change-bundle'
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import requests
import socketio

from .config import Config

logger = logging.getLogger("uhi-ha-bridge.uhi")


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
        def connect() -> None:  # noqa: WPS430
            logger.info("Socket.IO connected")

        @self._sio.event
        def disconnect() -> None:  # noqa: WPS430
            logger.warning("Socket.IO disconnected")

        @self._sio.on("uhi.collector.operationdata.change-bundle")
        def _on_bundle(data) -> None:  # noqa: WPS430
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

    def set_operation_mode(self, mode_id: int) -> dict:
        resp = self._session.put(
            self._url("/api/operationmode"), json={"id": mode_id}, timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def set_function_data(self, key: str, value) -> dict:
        resp = self._session.put(
            self._url(f"/api/functiondata/key/{key}"),
            json={"value": value},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

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
