"""Asynchronous client for the UHI (Dimplex System M).

Only existing endpoints/socket are used – NO change to the UHI.

- REST (aiohttp): read version, read/set operation mode, read/set function data
- Socket.IO (python-socketio asyncio, compatible with UHI socket.io server v2):
  live operating data via event 'uhi.collector.operationdata.change-bundle'
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
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


def _js_value(value: Any) -> Any:
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


def path_parts(path: str) -> list[str]:
    """'/api/v2/heatingunit/HK1/temperature?x' -> ['heatingunit', 'HK1', ...]."""
    parts = [p for p in path.split("?", 1)[0].split("/") if p]
    while parts and parts[0] in ("api", "v2"):
        parts.pop(0)
    return parts


def _route_from_path(path: str) -> str:
    """'/api/v2/functiondata/key/P_EVS' -> 'functiondata.key'.

    Heating units carry their id in the path:
    '/api/heatingunit/HK1/temperature' -> 'heatingunit.temperature'.
    """
    parts = path_parts(path)
    if len(parts) >= 3 and parts[0] == "heatingunit":
        return f"heatingunit.{parts[2]}"
    return ".".join(parts[:2])


def parse_api_response(data: Any) -> tuple[str, Any, str] | None:
    """Extract (route, body, path) from a successful 'api.response' broadcast.

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
    path = request.get("path") or request.get("url") or ""
    route = (request.get("headers") or {}).get("x-route") or (
        response.get("headers") or {}
    ).get("x-route")
    if not route:
        route = _route_from_path(path)
    body = response.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return None
    return (route, body, path) if route else None


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
        # Set by the coordinator.
        self.on_operationdata: Callable[[dict[str, Any]], Awaitable[None]] | None = (
            None
        )
        # Called on every (re)connect of the socket.
        self.on_connect: Callable[[], None] | None = None
        # Called with (route, body, path) for every successful 'api.response'.
        self.on_api_response: Callable[[str, Any, str], None] | None = None

    @property
    def socket_active(self) -> bool:
        """True once a socket session exists (incl. automatic reconnects)."""
        return self._sio is not None

    @property
    def socket_connected(self) -> bool:
        return self._sio is not None and self._sio.connected

    # ---------------- REST ----------------
    async def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
        expect: type = dict,
    ) -> Any:
        """Send a request; a response of another type than `expect` is empty."""
        headers = dict(self._headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                data=None if payload is None else encode_body(payload),
                headers=headers,
                # Writes run a script on the UHI; its proxy gives up after 60 s.
                timeout=aiohttp.ClientTimeout(total=30 if method == "GET" else 60),
            ) as resp:
                if resp.status in (401, 403):
                    raise UhiAuthError(f"HTTP {resp.status} at {path}")
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError as exc:
            raise UhiApiError(f"{method} {path} failed: {exc}") from exc
        return data if isinstance(data, expect) else expect()

    async def get_version(self) -> dict:
        return await self._request("GET", "/api/system/version")

    async def get_operation_mode_list(self) -> list[dict]:
        return await self._request("GET", "/api/operationmode/list", expect=list)

    async def get_serial_number(self) -> str | None:
        """Serial number of the heat pump manager (WPM), if known."""
        data = await self._request("GET", "/api/system/serialnumber")
        serial = data.get("serial_number") or data.get("wpm_serial_number")
        return str(serial) if serial else None

    async def get_operation_mode(self) -> dict:
        """Current mode: { id, is_automatic_mode, name, dateStart, ... }."""
        return await self._request("GET", "/api/operationmode")

    async def set_operation_mode(
        self, mode_id: int, is_automatic: bool, **extra: Any
    ) -> dict:
        """Set the mode; without is_automatic_mode the UHI turns automatic off."""
        payload = {"id": mode_id, "is_automatic_mode": int(is_automatic), **extra}
        return await self._request("PUT", "/api/operationmode", payload)

    async def set_function_data(self, key: str, value: Any) -> dict:
        return await self._request(
            "PUT", f"/api/functiondata/key/{key}", {"value": value}
        )

    async def get_heating_units(self) -> list[dict]:
        """Heating circuits, rooms, hot water and pool the user can adjust."""
        return await self._request("GET", "/api/heatingunit/config", expect=list)

    async def get_heating_unit_temperature(self, unit_id: str) -> dict:
        """Response: { current, target, offset }."""
        return await self._request("GET", f"/api/heatingunit/{unit_id}/temperature")

    async def set_heating_unit_target(self, unit_id: str, target: float) -> dict:
        """Response: { current, target, setoff }."""
        return await self._request(
            "PUT", f"/api/heatingunit/{unit_id}/temperature", {"target": target}
        )

    async def set_rapid_heating(self, unit_id: str, level: int) -> dict:
        """Response: { level, id }."""
        return await self._request(
            "POST", "/api/data/rapidheating", {"id": unit_id, "level": level}
        )

    async def get_system_status(self) -> dict:
        """Response: { uptime, current_error, cloud_connection, has_internet,
        simulation_mode }. has_internet is checked live (HTTPS, up to 10 s)."""
        return await self._request("GET", "/api/system/status")

    async def get_update_check(self) -> dict:
        """Ask the UHI whether the vendor offers a newer UHI version.

        Response: { oldRemoteUpdateStatus: { available, latest: { version } },
        applianceFirmwareUpdateStatus }. The UHI contacts the vendor server.
        """
        return await self._request("GET", "/api/system/update/check")

    async def get_update_status(self) -> dict:
        """Response: { code: 0 idle | 10 UHI | 20 WPM, state, current_step_no,
        total_step_no, ... }."""
        return await self._request("GET", "/api/system/update")

    async def start_update(self) -> dict:
        """Request the UHI update; the UHI updater starts it within ~10 s."""
        return await self._request("PUT", "/api/system/update", {})

    async def get_function_data_groups(self, groups: Iterable[str]) -> dict:
        """GET /api/functiondata/groups?groups=...

        Response: { GROUP: [ { key, value, definition }, ... ], ... }
        """
        return await self._request(
            "GET", "/api/functiondata/groups", params={"groups": ",".join(groups)}
        )

    # ---------------- Socket.IO ----------------
    async def connect_socket(self) -> None:
        url = self._base_url
        sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_delay=2,
            logger=False,
            engineio_logger=False,
        )

        @sio.event
        async def connect() -> None:
            _LOGGER.debug("Socket.IO connected (%s)", url)
            if self.on_connect:
                self.on_connect()

        @sio.event
        async def disconnect() -> None:
            _LOGGER.warning("Socket.IO disconnected")

        @sio.on(OPERATIONDATA_EVENT)
        async def _on_bundle(data: Any) -> None:
            values = data.get("payload") if isinstance(data, dict) else None
            if isinstance(values, dict) and self.on_operationdata:
                await self.on_operationdata(values)

        @sio.on(API_RESPONSE_EVENT)
        async def _on_api_response(data: Any) -> None:
            parsed = parse_api_response(data)
            if parsed is not None and self.on_api_response:
                self.on_api_response(*parsed)

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
            with suppress(Exception):
                await self._sio.disconnect()
            self._sio = None
