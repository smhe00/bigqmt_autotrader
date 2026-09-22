from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from bigqmt_autotrader.qmt.commands import broker_token_for

BRIDGE = (
    Path(__file__).resolve().parents[2]
    / "qmt_side"
    / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py"
)
DISABLED_DEPLOYMENTS = [BRIDGE.with_name("BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py")]


class Obj:
    pass


def load_bridge():
    spec = importlib.util.spec_from_file_location(
        "bigqmt_bridge_v05_guojin_sim", BRIDGE
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._STATE.account_id = "SIM_ACCOUNT"
    module._STATE.account_type = "STOCK"
    module._STATE.account_fingerprint = module.AUTHORIZED_ACCOUNT_FINGERPRINT
    module._STATE.session_id = "sim-session-01"
    return module


def command(bridge, command_type="SUBMIT_LIMIT", *, side="BUY", quantity=100, symbol="000001.SZ"):
    client_order_id = "sim-cal-001"
    token = broker_token_for(bridge.AUTHORIZED_ACCOUNT_FINGERPRINT, client_order_id)
    payload = {
        "simulation_calibration": True,
        "expected_qmt_session_id": bridge._STATE.session_id,
    }
    if command_type == "SUBMIT_LIMIT":
        payload.update(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "limit_price": "10.00",
            }
        )
    else:
        payload["broker_order_id"] = "broker-001"
    return {
        "command_type": command_type,
        "client_order_id": client_order_id,
        "broker_token": token,
        "payload": payload,
    }


def called_names(path: Path) -> set[str]:
    tree = ast.parse(
        path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 6)
    )
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_broker_mutation_surface_exists_only_in_pinned_simulation_artifact():
    assert {"passorder", "can_cancel_order", "cancel"} <= called_names(BRIDGE)
    for path in DISABLED_DEPLOYMENTS:
        assert not ({"passorder", "can_cancel_order", "cancel"} & called_names(path))
        source = path.read_text(encoding="utf-8")
        assert 'EXECUTION_MODE = "SHADOW"' in source
        assert "TRADING_ENABLED = False" in source
        assert "LIVE_SUBMIT_ENABLED = False" in source
        assert "LIVE_CANCEL_ENABLED = False" in source


def test_simulation_submit_is_pinned_bounded_and_preserves_broker_token(monkeypatch):
    bridge = load_bridge()
    observed = []
    monkeypatch.setattr(
        bridge, "passorder", lambda *args: observed.append(args), raising=False
    )

    result = bridge._execute_order_command(command(bridge), object())

    assert result == ("SIMULATION_SUBMIT_CALL_RETURNED", True)
    assert len(observed) == 1
    args = observed[0]
    assert args[:7] == (23, 1101, "SIM_ACCOUNT", "000001.SZ", 11, 10.0, 100)
    assert args[7:10] == ("BIGQMT_SIM_CAL", 2, command(bridge)["broker_token"])
    assert bridge._STATE.simulation_submit_calls == 1


def test_simulation_sell_and_sub_hundred_quantity_are_supported(monkeypatch):
    bridge = load_bridge()
    observed = []
    monkeypatch.setattr(
        bridge, "passorder", lambda *args: observed.append(args), raising=False
    )

    result = bridge._execute_order_command(
        command(bridge, side="SELL", quantity=10, symbol="204001.SH"), object()
    )

    assert result == ("SIMULATION_SUBMIT_CALL_RETURNED", True)
    assert observed[0][:7] == (24, 1101, "SIM_ACCOUNT", "204001.SH", 11, 10.0, 10)


@pytest.mark.parametrize("market", ["HK", "HGT", "SGT"])
def test_simulation_hong_kong_symbol_uses_same_bound_stock_account(monkeypatch, market):
    bridge = load_bridge()
    observed = []
    monkeypatch.setattr(
        bridge, "passorder", lambda *args: observed.append(args), raising=False
    )

    result = bridge._execute_order_command(
        command(bridge, side="BUY", quantity=100, symbol="00700." + market), object()
    )

    assert result == ("SIMULATION_SUBMIT_CALL_RETURNED", True)
    assert observed[0][:7] == (
        23,
        1101,
        "SIM_ACCOUNT",
        "00700." + market,
        11,
        10.0,
        100,
    )


def test_simulation_build_includes_stock_connect_runtime_diagnostics():
    bridge = load_bridge()

    assert bridge.BRIDGE_BUILD == "p5-simulation-calibration-8"
    assert bridge._SIMULATION_INSTRUMENT_CANDIDATES == (
        "204001.SH",
        "511880.SH",
        "00700.HK",
        "00700.HGT",
        "00700.SGT",
    )
    assert callable(bridge._runtime_instrument_probe)
    assert callable(bridge._runtime_instrument_subscribe)


def test_simulation_discovers_bounded_stock_connect_candidate_routes():
    bridge = load_bridge()

    class SectorContext:
        def get_tick_timetag(self):
            return 1789819797000

        def get_stock_list_in_sector(self, sector_name, realtime):
            assert realtime == 1789819797000
            if sector_name == "沪港通":
                return ["00700.HK", "09988.HK", "00941.HK", "bad.HK"]
            if sector_name == "深港通":
                return ["01810.HK", "03690.HK", "00981.HK", "00700.HK"]
            return []

    payload = bridge._simulation_discover_stock_connect_candidates(SectorContext())

    assert payload["method"] == "get_stock_list_in_sector"
    assert payload["realtime"] == 1789819797000
    assert payload["selected_underlyings"] == [
        "00700",
        "09988",
        "01810",
        "03690",
        "00941",
        "00981",
    ]
    assert payload["discovered_underlying_count"] == 6
    assert payload["fallback_used"] is False
    assert payload["fallback_underlyings"] == []
    assert payload["candidate_count"] == 20
    assert payload["truncated"] is False
    assert bridge._SIMULATION_INSTRUMENT_CANDIDATES[:2] == (
        "204001.SH",
        "511880.SH",
    )
    assert "09988.HK" in bridge._SIMULATION_INSTRUMENT_CANDIDATES
    assert "09988.HGT" in bridge._SIMULATION_INSTRUMENT_CANDIDATES
    assert "09988.SGT" in bridge._SIMULATION_INSTRUMENT_CANDIDATES
    assert len(bridge._SIMULATION_INSTRUMENT_CANDIDATES) == 20


def test_simulation_sector_discovery_uses_bounded_preferred_fallback():
    bridge = load_bridge()

    payload = bridge._simulation_discover_stock_connect_candidates(object())

    assert payload["error"] == "SECTOR_QUERY_UNAVAILABLE"
    assert payload["discovered_underlying_count"] == 0
    assert payload["fallback_used"] is True
    assert payload["selected_underlyings"] == [
        "00700",
        "09988",
        "01810",
        "03690",
        "00941",
        "00981",
    ]
    assert payload["fallback_underlyings"] == payload["selected_underlyings"]
    assert payload["candidate_count"] == 20
    assert len(bridge._SIMULATION_INSTRUMENT_CANDIDATES) == 20


def test_simulation_sector_discovery_fills_partial_result_with_preferred_codes():
    bridge = load_bridge()

    class SectorContext:
        def get_stock_list_in_sector(self, sector_name, realtime):
            if sector_name == "沪港通":
                return ["01211.HK", "00700.HK"]
            return []

    payload = bridge._simulation_discover_stock_connect_candidates(SectorContext())

    assert payload["discovered_underlying_count"] == 2
    assert payload["selected_underlyings"] == [
        "00700",
        "01211",
        "09988",
        "01810",
        "03690",
        "00941",
    ]
    assert payload["fallback_underlyings"] == [
        "09988",
        "01810",
        "03690",
        "00941",
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("simulation_calibration", False),
        ("expected_qmt_session_id", "stale-session"),
        ("quantity", 101),
        ("side", "SHORT"),
        ("symbol", "700.HK"),
    ],
)
def test_simulation_submit_safety_gate_rejects_out_of_scope_command(
    monkeypatch, field, value
):
    bridge = load_bridge()
    observed = []
    monkeypatch.setattr(
        bridge, "passorder", lambda *args: observed.append(args), raising=False
    )
    candidate = command(bridge)
    candidate["payload"][field] = value

    with pytest.raises(bridge.CommandError):
        bridge._execute_order_command(candidate, object())

    assert observed == []


def test_simulation_cancel_requires_exact_broker_id_and_remark(monkeypatch):
    bridge = load_bridge()
    candidate = command(bridge, "CANCEL_ORDER")
    order = Obj()
    order.m_strOrderSysID = "broker-001"
    order.m_strRemark = candidate["broker_token"]
    cancel_calls = []
    monkeypatch.setattr(
        bridge,
        "get_trade_detail_data",
        lambda *_args: [order],
        raising=False,
    )
    monkeypatch.setattr(bridge, "can_cancel_order", lambda *_args: True, raising=False)
    monkeypatch.setattr(
        bridge,
        "cancel",
        lambda *args: cancel_calls.append(args) or True,
        raising=False,
    )

    result = bridge._execute_order_command(candidate, object())

    assert result == ("SIMULATION_CANCEL_SIGNAL_SENT", True)
    assert len(cancel_calls) == 1
    assert cancel_calls[0][:3] == ("broker-001", "SIM_ACCOUNT", "STOCK")


def test_simulation_cancel_rejects_order_with_other_remark(monkeypatch):
    bridge = load_bridge()
    order = Obj()
    order.m_strOrderSysID = "broker-001"
    order.m_strRemark = "not-our-token"
    cancel_calls = []
    monkeypatch.setattr(
        bridge, "get_trade_detail_data", lambda *_args: [order], raising=False
    )
    monkeypatch.setattr(
        bridge,
        "cancel",
        lambda *args: cancel_calls.append(args) or True,
        raising=False,
    )

    with pytest.raises(bridge.CommandError):
        bridge._execute_order_command(command(bridge, "CANCEL_ORDER"), object())

    assert cancel_calls == []


def test_simulation_cancel_reports_terminal_order_without_calling_cancel(monkeypatch):
    bridge = load_bridge()
    candidate = command(bridge, "CANCEL_ORDER")
    order = Obj()
    order.m_strOrderSysID = "broker-001"
    order.m_strRemark = candidate["broker_token"]
    cancel_calls = []
    monkeypatch.setattr(
        bridge, "get_trade_detail_data", lambda *_args: [order], raising=False
    )
    monkeypatch.setattr(bridge, "can_cancel_order", lambda *_args: False, raising=False)
    monkeypatch.setattr(
        bridge,
        "cancel",
        lambda *args: cancel_calls.append(args) or True,
        raising=False,
    )

    result = bridge._execute_order_command(candidate, object())

    assert result == ("SIMULATION_CANCEL_NOT_CANCELLABLE", False)
    assert cancel_calls == []
    assert bridge._STATE.simulation_cancel_calls == 0


def test_simulation_submit_session_limit_rejects_before_over_limit_broker_call(
    monkeypatch,
):
    bridge = load_bridge()
    submit_calls = []
    monkeypatch.setattr(
        bridge,
        "passorder",
        lambda *args: submit_calls.append(args),
        raising=False,
    )

    bridge._STATE.simulation_submit_calls = bridge.SIMULATION_MAX_SUBMIT_CALLS - 1
    bridge._execute_order_command(command(bridge), object())
    with pytest.raises(bridge.CommandError, match="session limit reached"):
        bridge._execute_order_command(command(bridge), object())

    assert len(submit_calls) == 1
    assert (
        bridge._STATE.simulation_submit_calls == bridge.SIMULATION_MAX_SUBMIT_CALLS
    )


def test_snapshot_tick_refresh_repolls_already_observed_symbol(monkeypatch):
    bridge = load_bridge()
    bridge._SIMULATION_INSTRUMENT_CANDIDATES = ("00700.HGT",)
    state = bridge._tick_state()
    state["00700.HGT"] = {
        "symbol": "00700.HGT",
        "tick_observed": True,
        "callback_count": 1,
        "last_callback_ms": 1000,
        "evidence": {
            "requested_symbol": "00700.HGT",
            "reported_symbol": "00700.HGT",
            "exact_symbol": True,
            "tick_time": 1000,
            "last_price": "430.4",
        },
    }
    published = []

    class Context:
        def get_full_tick(self, symbols):
            assert symbols == ["00700.HGT"]
            return {
                "00700.HGT": {
                    "time": 2000,
                    "lastPrice": 450.4,
                    "volume": 10,
                    "amount": 4504,
                }
            }

    monkeypatch.setattr(
        bridge,
        "_publish_tick_capabilities",
        lambda source, final=False: (
            published.append((source, bridge._tick_capabilities_payload(final=final)))
            or published[-1][1]
        ),
    )
    monkeypatch.setattr(bridge.time, "time", lambda: 2.5)

    result = bridge._runtime_snapshot_tick_refresh(Context())

    record = bridge._tick_state()["00700.HGT"]
    assert result["attempted"] == 1
    assert result["observed"] == 1
    assert record["callback_count"] == 2
    assert record["last_callback_ms"] == 2500
    assert record["evidence"]["tick_time"] == 2000
    assert record["evidence"]["last_price"] == "450.4"
    assert published[-1][0] == "snapshot_tick_refresh"
    assert published[-1][1]["candidates"][0]["evidence"]["last_price"] == "450.4"


def test_snapshot_tick_refresh_mismatch_is_not_fresh_exact_evidence(monkeypatch):
    bridge = load_bridge()
    bridge._SIMULATION_INSTRUMENT_CANDIDATES = ("00700.HGT",)
    bridge._tick_state()["00700.HGT"] = {
        "symbol": "00700.HGT",
        "tick_observed": True,
        "callback_count": 1,
        "evidence": {
            "requested_symbol": "00700.HGT",
            "reported_symbol": "00700.HGT",
            "exact_symbol": True,
            "tick_time": 1000,
            "last_price": "430.4",
        },
    }

    class Context:
        def get_full_tick(self, symbols):
            return {"00700.HK": {"time": 3000, "lastPrice": 451.0}}

    monkeypatch.setattr(
        bridge,
        "_publish_tick_capabilities",
        lambda source, final=False: bridge._tick_capabilities_payload(final=final),
    )

    result = bridge._runtime_snapshot_tick_refresh(Context())

    evidence = bridge._tick_state()["00700.HGT"]["evidence"]
    assert result["observed"] == 0
    assert evidence["exact_symbol"] is False
    assert evidence["error"] == "TICK_CALLBACK_SYMBOL_MISMATCH"


def test_snapshot_tick_refresh_unavailable_is_read_only_and_fail_closed(monkeypatch):
    bridge = load_bridge()
    bridge._SIMULATION_INSTRUMENT_CANDIDATES = ("00700.HGT",)
    published = []
    monkeypatch.setattr(
        bridge,
        "_publish_tick_capabilities",
        lambda source, final=False: (
            published.append(source)
            or bridge._tick_capabilities_payload(final=final)
        ),
    )

    result = bridge._runtime_snapshot_tick_refresh(object())

    assert result["error"] == "GET_FULL_TICK_UNAVAILABLE"
    assert result["attempted"] == 0
    assert published == ["snapshot_tick_refresh_unavailable"]
    assert bridge._STATE.simulation_submit_calls == 0
    assert bridge._STATE.simulation_cancel_calls == 0


def test_request_snapshot_invokes_tick_refresh_hook(monkeypatch):
    bridge = load_bridge()
    calls = []
    monkeypatch.setattr(
        bridge,
        "_read_command_frame",
        lambda _path: {
            "expires_ms": int(bridge.time.time() * 1000) + 10000,
            "command_type": "REQUEST_SNAPSHOT",
            "command_id": "snapshot-refresh-test",
        },
    )
    monkeypatch.setattr(bridge, "read_account_capabilities", lambda: calls.append("accounts"))
    monkeypatch.setattr(bridge, "read_snapshot", lambda: calls.append("snapshot"))
    monkeypatch.setattr(
        bridge,
        "_runtime_snapshot_tick_refresh",
        lambda _context: calls.append("tick_refresh"),
    )
    monkeypatch.setattr(bridge, "flush_transport", lambda: calls.append("flush"))
    monkeypatch.setattr(bridge, "_atomic_move", lambda *_args: calls.append("move"))
    monkeypatch.setattr(bridge, "_command_dir", lambda name: name)
    monkeypatch.setattr(
        bridge,
        "_command_result",
        lambda _command, status, live_side_effect=False: calls.append(
            ("result", status, live_side_effect)
        ),
    )

    bridge._process_claimed("claimed", "snapshot.json", object())

    assert calls[:4] == ["accounts", "snapshot", "tick_refresh", "flush"]
    assert ("result", "SNAPSHOT_EMITTED", False) in calls
    assert bridge._STATE.simulation_submit_calls == 0
    assert bridge._STATE.simulation_cancel_calls == 0
