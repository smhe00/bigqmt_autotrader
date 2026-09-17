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


def test_simulation_hong_kong_symbol_uses_same_bound_stock_account(monkeypatch):
    bridge = load_bridge()
    observed = []
    monkeypatch.setattr(
        bridge, "passorder", lambda *args: observed.append(args), raising=False
    )

    result = bridge._execute_order_command(
        command(bridge, side="BUY", quantity=100, symbol="00700.HK"), object()
    )

    assert result == ("SIMULATION_SUBMIT_CALL_RETURNED", True)
    assert observed[0][:7] == (23, 1101, "SIM_ACCOUNT", "00700.HK", 11, 10.0, 100)


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
