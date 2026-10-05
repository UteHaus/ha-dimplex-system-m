"""Asynchronous client for the UHI (Dimplex System M).

Only existing endpoints/socket are used – NO change to the UHI.

- REST (aiohttp): read version, read/set operation mode, read/set function data
- Socket.IO (python-socketio asyncio, compatible with UHI socket.io server v2):
  live operating data via event 'uhi.collector.operationdata.change-bundle'
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
import json
import logging
from typing import Any

import aiohttp
import socketio

from .const import API_RESPONSE_EVENT, OPERATIONDATA_EVENT, SOCKETIO_PATH

_LOGGER = logging.getLogger(__name__)


class UhiApiError(Exception):
    """Generic error during UHI communication."""


class UhiAuthError(UhiApiError):
    """Authentication failed (401/403)."""


def _route_from_path(path: str) -> str:
    """'/api/v2/functiondata/key/P_EVS?x' -> 'functiondata.key'."""
    parts = [p for p in path.split("?", 1)[0].split("/") if p]
    while parts and parts[0] in ("api", "v2"):
        parts.pop(0)
    return ".".join(parts[:2])


def parse_api_response(data: Any) -> tuple[str, Any] | None:
    """Extract (route, body) from a successful 'api.response' broadcast.

    Payload: { request: { headers, path, ... }, response: { statusCode,
    headers, body } }. The route is the client's or the UHI's 'x-route'
    header; requests without one (like ours) fall back to the URL path.
    """
    if not isinstance(data, dict):
        return None
    request = data.get("request") or {}
    response = data.get("response") or {}
    if not isinstance(request, dict) or not isinstance(response, dict):
        return None
    if response.get("statusCode") != 200:
        return None
    route = (request.get("headers") or {}).get("x-route") or (
        response.get("headers") or {}
    ).get("x-route")
    if not route:
        route = _route_from_path(request.get("path") or request.get("url") or "")
    body = response.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return None
    return (route, body) if route else None


class UhiApiClient:
    """Wraps REST and Socket.IO access to a UHI instance."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        token: str | None = None,
        device_id: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._headers: dict[str, str] = {}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        if device_id:
            self._headers["Device"] = device_id

        self._sio: socketio.AsyncClient | None = None
        self._on_operationdata: (
            Callable[[dict[str, Any]], Awaitable[None]] | None
        ) = None
        self._on_connect: Callable[[], None] | None = None
        self._on_api_response: Callable[[str, Any], None] | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def socket_active(self) -> bool:
        """True once a socket session exists (incl. automatic reconnects)."""
        return self._sio is not None

    @property
    def socket_connected(self) -> bool:
        return self._sio is not None and self._sio.connected

    # ---------------- REST ----------------
    async def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.get(
                url,
                params=params,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (401, 403):
                    raise UhiAuthError(f"HTTP {resp.status} at {path}")
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as exc:
            raise UhiApiError(f"GET {path} failed: {exc}") from exc

    async def _put(self, path: str, payload: dict) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.put(
                url,
                json=payload,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (401, 403):
                    raise UhiAuthError(f"HTTP {resp.status} at {path}")
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as exc:
            raise UhiApiError(f"PUT {path} failed: {exc}") from exc

    async def get_version(self) -> dict:
        data = await self._get("/api/system/version")
        return data if isinstance(data, dict) else {}

    async def get_operation_mode_list(self) -> list[dict]:
        data = await self._get("/api/operationmode/list")
        return data if isinstance(data, list) else []

    async def get_serial_number(self) -> str | None:
        """Serial number of the heat pump manager (WPM), if known."""
        data = await self._get("/api/system/serialnumber")
        if not isinstance(data, dict):
            return None
        serial = data.get("serial_number") or data.get("wpm_serial_number")
        return str(serial) if serial else None

    async def get_operation_mode(self) -> dict:
        """Current mode: { id, is_automatic_mode, name, dateStart, ... }."""
        data = await self._get("/api/operationmode")
        return data if isinstance(data, dict) else {}

    async def set_operation_mode(
        self, mode_id: int, is_automatic: bool, **extra: Any
    ) -> dict:
        """Set the mode; without is_automatic_mode the UHI turns automatic off."""
        payload = {"id": mode_id, "is_automatic_mode": int(is_automatic), **extra}
        data = await self._put("/api/operationmode", payload)
        return data if isinstance(data, dict) else {}

    async def set_function_data(self, key: str, value: Any) -> dict:
        data = await self._put(f"/api/functiondata/key/{key}", {"value": value})
        return data if isinstance(data, dict) else {}

    async def get_function_data_groups(self, groups: Iterable[str]) -> dict:
        """GET /api/functiondata/groups?groups=...

        Response: { GROUP: [ { key, value, definition }, ... ], ... }
        """
        data = await self._get(
            "/api/functiondata/groups", params={"groups": ",".join(groups)}
        )
        return data if isinstance(data, dict) else {}

    # ---------------- Socket.IO ----------------
    def set_operationdata_handler(
        self, handler: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None:
        self._on_operationdata = handler

    def set_connect_handler(self, handler: Callable[[], None]) -> None:
        """Called on every (re)connect of the socket."""
        self._on_connect = handler

    def set_api_response_handler(self, handler: Callable[[str, Any], None]) -> None:
        """Called with (route, body) for every successful 'api.response'."""
        self._on_api_response = handler

    async def connect_socket(self, socket_url: str | None = None) -> None:
        url = (socket_url or self._base_url).rstrip("/")
        sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_delay=2,
            logger=False,
            engineio_logger=False,
        )

        @sio.event
        async def connect() -> None:
            _LOGGER.debug("Socket.IO connected (%s)", url)
            if self._on_connect:
                self._on_connect()

        @sio.event
        async def disconnect() -> None:
            _LOGGER.warning("Socket.IO disconnected")

        @sio.on(OPERATIONDATA_EVENT)
        async def _on_bundle(data: Any) -> None:
            values = data.get("payload") if isinstance(data, dict) else None
            if isinstance(values, dict) and self._on_operationdata:
                await self._on_operationdata(values)

        @sio.on(API_RESPONSE_EVENT)
        async def _on_api_response(data: Any) -> None:
            parsed = parse_api_response(data)
            if parsed is not None and self._on_api_response:
                self._on_api_response(*parsed)

        # python-socketio only reconnects automatically after a successful
        # first connect; a failed attempt leaves no session behind so the
        # caller can retry.
        await sio.connect(
            url,
            socketio_path=SOCKETIO_PATH,
            transports=["websocket", "polling"],
        )
        self._sio = sio

    async def disconnect_socket(self) -> None:
        if self._sio is not None:
            try:
                await self._sio.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._sio = None
