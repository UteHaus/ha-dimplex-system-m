"""Tests for dimplex_uhi (UHI 4.3.4 on the device; 3.x formats as fallback)."""

import json
from unittest.mock import AsyncMock, PropertyMock, patch

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import DATA_RESTORE_STATE, StoredState
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

import custom_components.dimplex_uhi.api  # noqa: F401
from custom_components.dimplex_uhi.api import (
    UhiApiClient,
    UhiApiError,
    parse_api_response,
)

DOMAIN = "dimplex_uhi"
SERIAL = "WPM123456"
BASE = "custom_components.dimplex_uhi.api.UhiApiClient"

GROUPS = {
    "GROUP_01": [
        {
            "key": "E_Aussen_T",
            "value": "5.5",
            "definition": {"physicalUnit": "UNIT_DEG_C"},
        },
        {
            "key": "P_WW_SOLL",
            "value": "48",
            "definition": {"physicalUnit": "UNIT_DEG_C"},
        },
        {"key": "WPIO2_r_ECT_AC_Inp_Power", "value": "1000", "definition": {}},
    ]
}
# UHI 3.1.4: no MAC; mode ids are strings; GET operationmode is not wrapped.
VERSION = {"uhi": {"version": "3.1.4"}, "heatpump": "x"}
MODES = [
    {"id": "0", "name": "Sommer"},
    {"id": "1", "name": "Winter"},
    {"id": "3", "name": "Party"},
]
MODE = {"id": 1, "is_automatic_mode": 1, "name": "Winter", "dateStart": None}


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations):
    yield


@pytest.fixture
def api():
    mocks = {
        "get_version": AsyncMock(return_value=VERSION),
        "get_serial_number": AsyncMock(return_value=SERIAL),
        "get_operation_mode_list": AsyncMock(return_value=MODES),
        "get_operation_mode": AsyncMock(return_value=dict(MODE)),
        "set_operation_mode": AsyncMock(
            side_effect=lambda mode_id, auto, **kw: {
                "id": mode_id,
                "is_automatic_mode": int(auto),
            }
        ),
        "set_function_data": AsyncMock(
            side_effect=lambda key, value: {"key": key, "value": float(value)}
        ),
        "get_function_data_groups": AsyncMock(return_value=GROUPS),
        "connect_socket": AsyncMock(),
        "disconnect_socket": AsyncMock(),
    }
    patches = [patch(f"{BASE}.{name}", mock) for name, mock in mocks.items()]
    for p in patches:
        p.start()
    yield mocks
    for p in patches:
        p.stop()


async def _setup(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={"name": "WP", "host": "uhi", "port": 8080, "language": "de"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


def _state(hass, unique_suffix):
    ent_reg = er.async_get(hass)
    for platform in ("select", "switch", "number", "sensor"):
        eid = ent_reg.async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{unique_suffix}")
        if eid:
            return hass.states.get(eid)
    raise AssertionError(unique_suffix)


async def test_mode_and_automatic_initialized(hass: HomeAssistant, api) -> None:
    await _setup(hass)
    assert _state(hass, "BA_aktiv").state == "Winter"
    assert _state(hass, "P_TBaUs").state == "on"


async def test_select_mode_keeps_automatic_and_party_end(
    hass: HomeAssistant, api
) -> None:
    await _setup(hass)
    mode = _state(hass, "BA_aktiv")
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": mode.entity_id, "option": "Sommer"},
        blocking=True,
    )
    api["set_operation_mode"].assert_awaited_with(0, True)
    assert hass.states.get(mode.entity_id).state == "Sommer"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": mode.entity_id, "option": "Party"},
        blocking=True,
    )
    args, kwargs = api["set_operation_mode"].await_args
    assert args == (3, True) and "dateEnd" in kwargs


async def test_automatic_switch(hass: HomeAssistant, api) -> None:
    _, coord = await _setup(hass)
    sw = _state(hass, "P_TBaUs")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": sw.entity_id}, blocking=True
    )
    api["set_operation_mode"].assert_awaited_with(1, False)
    assert hass.states.get(sw.entity_id).state == "off"
    coord.current_mode_id = 3
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": sw.entity_id}, blocking=True
        )


async def test_restore_live_and_write(hass: HomeAssistant, api) -> None:
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "number", DOMAIN, f"{SERIAL}_P_HK1_WK", suggested_object_id="wk"
    )
    ent_reg.async_get_or_create(
        "select", DOMAIN, f"{SERIAL}_P_EVS", suggested_object_id="evs"
    )
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("number.wk", "12"),
                {
                    "native_value": 12.0,
                    "native_min_value": -19,
                    "native_max_value": 38,
                    "native_step": 1,
                    "native_unit_of_measurement": None,
                },
            )
        ],
    )
    hass.data[DATA_RESTORE_STATE].last_states["select.evs"] = StoredState(
        State("select.evs", "Dauerhaft"), None, dt_util.utcnow()
    )
    _, coord = await _setup(hass)
    assert float(hass.states.get("number.wk").state) == 12
    assert hass.states.get("select.evs").state == "Dauerhaft"

    await coord._handle_live_values({"BA_aktiv": 0, "P_HK1_WK": 20})
    await hass.async_block_till_done()
    assert _state(hass, "BA_aktiv").state == "Sommer"
    assert float(hass.states.get("number.wk").state) == 20

    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.wk", "value": 5}, blocking=True
    )
    api["set_function_data"].assert_awaited_with("P_HK1_WK", 5)
    assert float(hass.states.get("number.wk").state) == 5

    api["set_function_data"].side_effect = UhiApiError("HTTP 500")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": "number.wk", "value": 7}, blocking=True
        )
    assert float(hass.states.get("number.wk").state) == 5

    result = await hass.config_entries.options.async_init(coord.entry.entry_id)
    assert result["type"] == "form"


async def test_socket_retry_and_refresh_on_connect(hass: HomeAssistant, api) -> None:
    api["connect_socket"].side_effect = ConnectionError("down")
    _, coord = await _setup(hass)
    assert api["connect_socket"].await_count == 1
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert api["connect_socket"].await_count == 2

    calls = api["get_function_data_groups"].await_count
    coord._handle_socket_connect()  # first connect after setup: no extra poll
    await hass.async_block_till_done()
    assert api["get_function_data_groups"].await_count == calls
    coord._handle_socket_connect()  # reconnect: catch up
    await hass.async_block_till_done()
    assert api["get_function_data_groups"].await_count == calls + 1


async def test_connected_socket_skips_snapshot(hass: HomeAssistant, api) -> None:
    _, coord = await _setup(hass)
    calls = api["get_function_data_groups"].await_count
    with patch.object(
        UhiApiClient, "socket_connected", new_callable=PropertyMock, return_value=True
    ):
        await coord.async_refresh()
        assert api["get_function_data_groups"].await_count == calls
        coord._last_snapshot -= 601
        await coord.async_refresh()
        assert api["get_function_data_groups"].await_count == calls + 1


def _api_response(body, path="", x_route=None, status=200):
    headers = {"x-route": x_route} if x_route else {}
    return {
        "request": {"headers": headers, "path": path},
        "response": {"statusCode": status, "headers": {}, "body": json.dumps(body)},
        "_meta": {},
    }


def test_parse_api_response() -> None:
    body = {"key": "P_EVS", "value": 2.0}
    assert parse_api_response(_api_response(body, x_route="functiondata.key")) == (
        "functiondata.key",
        body,
    )
    assert parse_api_response(
        _api_response(body, path="/api/v2/functiondata/key/P_EVS")
    ) == ("functiondata.key", body)
    assert parse_api_response(_api_response({}, path="/api/operationmode")) == (
        "operationmode",
        {},
    )
    assert parse_api_response(_api_response(body, status=500)) is None
    assert parse_api_response("garbage") is None


async def test_api_response_pushes(hass: HomeAssistant, api) -> None:
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "select", DOMAIN, f"{SERIAL}_P_EVS", suggested_object_id="evs"
    )
    _, coord = await _setup(hass)
    handle = coord._handle_api_response

    # Write on the touch display (not part of the change bundles).
    handle("functiondata.key", {"key": "P_EVS", "value": 2.0})
    await hass.async_block_till_done()
    assert hass.states.get("select.evs").state == "Dauerhaft"

    # Re-broadcast group snapshot.
    handle(
        "functiondata.groups",
        {"GROUP_01": [{"key": "P_WW_SOLL", "value": "52", "definition": {}}]},
    )
    assert coord.data["P_WW_SOLL"] == "52"

    # Operation mode incl. automatic flag; the list response is ignored.
    handle("operationmode", {"id": 0, "is_automatic_mode": 0, "name": "Sommer"})
    handle("operationmode.list", [{"id": "1", "name": "Winter"}])
    await hass.async_block_till_done()
    assert _state(hass, "BA_aktiv").state == "Sommer"
    assert _state(hass, "P_TBaUs").state == "off"


async def test_energy_left_riemann(hass: HomeAssistant, api) -> None:
    _, coord = await _setup(hass)
    energy = _state(hass, "ac_input_energy")
    ent = hass.data["sensor"].get_entity(energy.entity_id)
    ent._last_ts -= 3599  # pretend 1000 W held for (almost) one hour
    await coord._handle_live_values({"WPIO2_r_ECT_AC_Inp_Power": 0})
    assert ent.native_value == pytest.approx(1.0, abs=1e-3)


async def test_config_flow_uses_serial_without_mac(hass: HomeAssistant, api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    with patch("custom_components.dimplex_uhi.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "WP", "host": "uhi", "language": "de"}
        )
    assert result["type"] == "create_entry"
    assert result["result"].unique_id == SERIAL
