"""Tests for dimplex_uhi (UHI 4.3.4 on the device; 3.x formats as fallback)."""

import json
import time
from unittest.mock import AsyncMock, PropertyMock, patch

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

import custom_components.dimplex_uhi.api  # noqa: F401
from custom_components.dimplex_uhi.api import (
    UhiApiClient,
    UhiApiError,
    encode_body,
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
    ],
    "MISC": [
        {
            "key": "P_WW_MIN_TEMP",
            "value": 40,
            "definition": {"physicalUnit": "UNIT_DEG_C"},
        }
    ],
    "INPUTS": [
        {"key": "SmartGrid_Niedrig", "value": 0, "definition": {}},
        {"key": "SmartGrid_Hoch", "value": 0, "definition": {}},
        {"key": "SmartGrid_Normal", "value": 1, "definition": {}},
        {"key": "SmartGrid_Problem", "value": 0, "definition": {}},
    ],
}
# /api/heatingunit/config as reported by the UHI 4.3.4 on the heat pump.
HEATING_UNITS = [
    {
        "type": "HK_VERSCHIEBUNG",
        "setTemperature": True,
        "targetTemperature": {"min": -19, "max": 19},
        "id": "HK1",
        "variableValues": {
            "current": 23.5,
            "target": 1,
            "offset": 0,
            "rapidheating": {"level": 0},
        },
        "capabilities": {"set_temperature_delta": 1},
        "name": "HK1",
    },
    {
        "type": "WARMWASSER",
        "setTemperature": True,
        "targetTemperature": {"min": 30, "max": 60},
        "id": "WW",
        "variableValues": {"current": 48.9, "target": 50, "offset": 0},
        "capabilities": {},
        "name": "WW",
    },
    # Pool configured in the WPM but without a reading: not created.
    {
        "type": "SCHWIMMBAD",
        "setTemperature": True,
        "targetTemperature": {"min": 10, "max": 35},
        "id": "SW",
        "capabilities": {},
        "name": "SW",
    },
]
# UHI 3.1.4: no MAC; mode ids are strings; GET operationmode is not wrapped.
VERSION = {"uhi": {"version": "3.1.4"}, "heatpump": "x"}
MODES = [
    {"id": "0", "name": "Sommer"},
    {"id": "1", "name": "Winter"},
    {"id": "3", "name": "Party"},
]
MODE = {
    "id": 1,
    "is_automatic_mode": 1,
    "name": "Winter",
    "dateStart": None,
    "limitTempCooling": 25,
    "limitTempHeating": 18,
    "delayTimeHours": 3,
}


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
        "get_heating_units": AsyncMock(
            side_effect=lambda: json.loads(json.dumps(HEATING_UNITS))
        ),
        "get_heating_unit_temperature": AsyncMock(
            return_value={"current": 0, "target": 25, "offset": 0}
        ),
        "set_heating_unit_target": AsyncMock(
            side_effect=lambda unit_id, target: {"current": 20, "target": target}
        ),
        "set_rapid_heating": AsyncMock(
            side_effect=lambda unit_id, level: {"level": level, "id": unit_id}
        ),
        "connect_socket": AsyncMock(),
        "disconnect_socket": AsyncMock(),
    }
    patches = [patch(f"{BASE}.{name}", mock) for name, mock in mocks.items()]
    for p in patches:
        p.start()
    yield mocks
    for p in patches:
        p.stop()


async def _setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={"name": "WP", "host": "uhi", "port": 8080, "language": "de"},
        options=options or {},
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


async def test_commissioning_parameters_read_only(hass: HomeAssistant, api) -> None:
    """No read endpoint: restored, updated by pushes, never writable."""
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{SERIAL}_P_HK1_END", suggested_object_id="hk1_end"
    )
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("sensor.hk1_end", "45"),
                {"native_value": 45, "native_unit_of_measurement": "°C"},
            )
        ],
    )
    _, coord = await _setup(hass)
    end = hass.states.get("sensor.hk1_end")
    assert end.state == "45"
    assert "Inbetriebnahme" in end.attributes["info"]
    assert ent_reg.async_get_entity_id("number", DOMAIN, f"{SERIAL}_P_HK1_END") is None
    assert ent_reg.async_get_entity_id("select", DOMAIN, f"{SERIAL}_P_EVS") is None

    evs = _state(hass, "P_EVS")
    assert evs.state == "unknown"
    await coord._handle_live_values({"P_EVS": 2, "P_HK1_END": 48})
    await hass.async_block_till_done()
    assert _state(hass, "P_EVS").state == "Dauerhaft"
    assert hass.states.get("sensor.hk1_end").state == "48"

    result = await hass.config_entries.options.async_init(coord.entry.entry_id)
    assert result["type"] == "form"


async def test_heating_units(hass: HomeAssistant, api) -> None:
    await _setup(hass)
    hk1 = _state(hass, "heatingunit_HK1")
    assert hk1.state == "1"
    assert (hk1.attributes["min"], hk1.attributes["max"]) == (-19, 19)
    assert hk1.attributes["unit_of_measurement"] == "K"
    ww = _state(hass, "P_WW_SOLL")  # took over the former P_WW_SOLL number
    assert ww.state == "50"
    assert (ww.attributes["min"], ww.attributes["max"]) == (30, 60)
    ent_reg = er.async_get(hass)
    assert (
        ent_reg.async_get_entity_id("number", DOMAIN, f"{SERIAL}_heatingunit_SW")
        is None
    )

    await hass.services.async_call(
        "number", "set_value", {"entity_id": hk1.entity_id, "value": 3}, blocking=True
    )
    api["set_heating_unit_target"].assert_awaited_with("HK1", 3)
    assert hass.states.get(hk1.entity_id).state == "3"

    # Not below the hot water minimum (P_WW_MIN_TEMP = 40), like the UHI app.
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": ww.entity_id, "value": 35},
            blocking=True,
        )
    api["set_heating_unit_target"].side_effect = UhiApiError("HTTP 500")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": ww.entity_id, "value": 55},
            blocking=True,
        )
    assert hass.states.get(ww.entity_id).state == "50"


async def test_rapid_heating(hass: HomeAssistant, api) -> None:
    await _setup(hass)
    rapid = _state(hass, "rapidheating_HK1")
    assert rapid.state == "Aus"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": rapid.entity_id, "option": "Stufe 2"},
        blocking=True,
    )
    api["set_rapid_heating"].assert_awaited_with("HK1", 2)
    assert hass.states.get(rapid.entity_id).state == "Stufe 2"


async def test_mode_limits(hass: HomeAssistant, api) -> None:
    _, coord = await _setup(hass)
    heating = _state(hass, "mode_limitTempHeating")
    assert heating.state == "18"
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": heating.entity_id, "value": 16},
        blocking=True,
    )
    args, kwargs = api["set_operation_mode"].await_args
    assert args == (1, True)
    assert kwargs == {
        "limitTempHeating": 16,
        "limitTempCooling": 25,
        "delayTimeHours": 3,
    }
    assert hass.states.get(heating.entity_id).state == "16"

    coord.is_automatic = False
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": heating.entity_id, "value": 15},
            blocking=True,
        )


async def test_smart_grid_state(hass: HomeAssistant, api) -> None:
    _, coord = await _setup(hass)
    assert _state(hass, "smart_grid").state == "Normal"
    await coord._handle_live_values({"SmartGrid_Normal": 0, "SmartGrid_Hoch": 1})
    await hass.async_block_till_done()
    assert _state(hass, "smart_grid").state == "Hoch"


async def test_no_smart_grid_control(hass: HomeAssistant, api) -> None:
    """The UHI cannot write the Smart Grid flags: status only, no control."""
    await _setup(hass)
    ent_reg = er.async_get(hass)
    assert (
        ent_reg.async_get_entity_id("select", DOMAIN, f"{SERIAL}_smart_grid_request")
        is None
    )


async def test_ww_min_write(hass: HomeAssistant, api) -> None:
    await _setup(hass)
    ww_min = _state(hass, "P_WW_MIN_TEMP")
    assert ww_min.state == "40"
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": ww_min.entity_id, "value": 45},
        blocking=True,
    )
    api["set_function_data"].assert_awaited_with("P_WW_MIN_TEMP", 45)
    assert hass.states.get(ww_min.entity_id).state == "45"


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
        await coord._handle_live_values({"E_Aussen_T": "5.6"})
        await coord.async_refresh()
        assert api["get_function_data_groups"].await_count == calls
        coord._last_snapshot -= 601
        await coord.async_refresh()
        assert api["get_function_data_groups"].await_count == calls + 1


async def test_silent_socket_polls_again(hass: HomeAssistant, api) -> None:
    """Connected but no change bundles (e.g. event renamed): poll as usual."""
    _, coord = await _setup(hass)
    calls = api["get_function_data_groups"].await_count
    with patch.object(
        UhiApiClient, "socket_connected", new_callable=PropertyMock, return_value=True
    ):
        coord._last_bundle = time.monotonic() - 301
        await coord.async_refresh()
    assert api["get_function_data_groups"].await_count == calls + 1


async def test_unknown_group_is_skipped(hass: HomeAssistant, api) -> None:
    """One group the UHI rejects must not take the whole integration down."""

    async def groups(names):
        if len(names) > 1 or names == ["MISC"]:
            raise UhiApiError("HTTP 500")
        return {names[0]: GROUPS["GROUP_01"] if names[0] == "GROUP_01" else []}

    api["get_function_data_groups"].side_effect = groups
    _, coord = await _setup(hass)
    assert coord.last_update_success
    assert coord.data["E_Aussen_T"] == "5.5"
    assert "MISC" in coord._skipped_groups

    api["get_function_data_groups"].reset_mock()
    await coord.async_refresh()
    first_call = api["get_function_data_groups"].await_args_list[0].args[0]
    assert "MISC" not in first_call and "GROUP_01" in first_call


async def test_unreachable_uhi_skips_no_group(hass: HomeAssistant, api) -> None:
    _, coord = await _setup(hass)
    api["get_function_data_groups"].side_effect = UhiApiError("timeout")
    await coord.async_refresh()
    assert not coord.last_update_success
    assert coord._skipped_groups == {}


async def test_number_limits_prefer_uhi(hass: HomeAssistant, api) -> None:
    _, coord = await _setup(hass)
    number = _state(hass, "P_WW_MIN_TEMP")
    assert number.attributes["min"] == 10  # hard-coded spec
    coord._handle_api_response(
        "functiondata.groups",
        {
            "MISC": [
                {
                    "key": "P_WW_MIN_TEMP",
                    "value": 40,
                    "definition": {"numberMin": 35, "numberMax": 60},
                }
            ]
        },
    )
    await hass.async_block_till_done()
    number = hass.states.get(number.entity_id)
    assert (number.attributes["min"], number.attributes["max"]) == (35, 60)


def _api_response(body, path="", x_route=None, status=200):
    headers = {"x-route": x_route} if x_route else {}
    return {
        "request": {"headers": headers, "path": path},
        "response": {"statusCode": status, "headers": {}, "body": json.dumps(body)},
        "_meta": {},
    }


def test_encode_body_matches_json_stringify() -> None:
    """Same bytes as JSON.stringify, else the UHI's internal proxy hangs."""
    assert encode_body({"value": 10}) == b'{"value":10}'
    assert encode_body({"value": 45.0}) == b'{"value":45}'
    assert encode_body({"value": 45.5}) == b'{"value":45.5}'
    assert encode_body({"id": 1, "name": "Wärme"}) == '{"id":1,"name":"Wärme"}'.encode()


def test_parse_api_response() -> None:
    body = {"key": "P_EVS", "value": 2.0}
    assert parse_api_response(_api_response(body, x_route="functiondata.key")) == (
        "functiondata.key",
        body,
        "",
    )
    path = "/api/v2/functiondata/key/P_EVS"
    assert parse_api_response(_api_response(body, path=path)) == (
        "functiondata.key",
        body,
        path,
    )
    path = "/api/heatingunit/HK1/temperature"
    assert parse_api_response(_api_response({"target": 2}, path=path)) == (
        "heatingunit.temperature",
        {"target": 2},
        path,
    )
    assert parse_api_response(_api_response(body, status=500)) is None
    assert parse_api_response("garbage") is None


async def test_api_response_pushes(hass: HomeAssistant, api) -> None:
    _, coord = await _setup(hass)
    handle = coord._handle_api_response

    # Write on the touch display (not part of the change bundles).
    handle("functiondata.key", {"key": "P_WW_MIN_TEMP", "value": 42.0})
    await hass.async_block_till_done()
    assert float(_state(hass, "P_WW_MIN_TEMP").state) == 42

    # Heating unit setpoint and rapid heating changed in the UHI app.
    handle(
        "heatingunit.temperature",
        {"current": 23, "target": -2, "offset": 0},
        "/api/v2/heatingunit/HK1/temperature",
    )
    handle("heatingunit.rapidheating", {"level": 3, "id": "HK1"})
    await hass.async_block_till_done()
    assert _state(hass, "heatingunit_HK1").state == "-2"
    assert _state(hass, "rapidheating_HK1").state == "Stufe 3"

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


async def test_entity_migration(hass: HomeAssistant, api) -> None:
    """Replaced entities keep their ids; area-prefixed ids are renamed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title="WP",
        data={"name": "WP", "host": "uhi", "port": 8080, "language": "de"},
    )
    entry.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Keller")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, SERIAL)}
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    ent_reg = er.async_get(hass)

    def old(domain, key, object_id):
        return ent_reg.async_get_or_create(
            domain,
            DOMAIN,
            f"{SERIAL}_{key}",
            config_entry=entry,
            suggested_object_id=object_id,
        ).entity_id

    old("number", "P_HK1_END", "wp_heizkurvenendpunkt")
    old("select", "P_EVS", "wp_evu_sperre")
    old("number", "P_HK1_WK", "wp_parameter_heizkreis_1_wk")
    old("sensor", "P_WW_MIN_TEMP", "wp_minimaltemperatur")
    old("number", "P_WW_SOLL", "wp_warmwassersolltemperatur")
    old("select", "rapidheating_HK1", "keller_wp_hk1_schnellaufheizung")
    old("sensor", "E_Vorl_T", "wp_vorlauftemperatur")
    old("sensor", "E_Vorl_T_WP", "keller_wp_vorlauftemperatur")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    def uid(entity_id):
        reg_entry = ent_reg.async_get(entity_id)
        return reg_entry.unique_id if reg_entry else None

    # Read-only now: same object id, sensor domain; old entities removed.
    assert uid("sensor.wp_heizkurvenendpunkt") == f"{SERIAL}_P_HK1_END"
    assert uid("sensor.wp_evu_sperre") == f"{SERIAL}_P_EVS"
    assert uid("number.wp_heizkurvenendpunkt") is None
    assert uid("select.wp_evu_sperre") is None
    # No successor / now a setting: removed.
    assert uid("number.wp_parameter_heizkreis_1_wk") is None
    assert uid("sensor.wp_minimaltemperatur") is None
    # Hot water setpoint keeps its entity.
    assert hass.states.get("number.wp_warmwassersolltemperatur").state == "50"
    # Area prefix generated by HA removed; new entities without area.
    assert uid("select.wp_hk1_schnellaufheizung") == f"{SERIAL}_rapidheating_HK1"
    assert uid("number.wp_automatik_heizgrenze") == f"{SERIAL}_mode_limitTempHeating"
    assert uid("sensor.wp_smart_grid") == f"{SERIAL}_smart_grid"
    # Target taken by another entity: next free id, nothing overwritten.
    assert uid("sensor.wp_vorlauftemperatur") == f"{SERIAL}_E_Vorl_T"
    assert uid("sensor.wp_vorlauftemperatur_2") == f"{SERIAL}_E_Vorl_T_WP"
