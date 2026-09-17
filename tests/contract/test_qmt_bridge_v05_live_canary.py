from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from bigqmt_autotrader.qmt.commands import broker_token_for


BRIDGE = (
    Path(__file__).resolve().parents[2]
    / "qmt_side"
    / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py"
)


class Obj:
    pass


class Context:
    def get_instrument_detail(self, symbol):
        assert symbol == "00700.SGT"
        return {"ExchangeID": "SGT", "InstrumentID": "00700", "IsTrading": True}


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_v05_guojin", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._STATE.account_id = "LIVE_ACCOUNT"
    module._STATE.account_type = "STOCK"
    module._STATE.account_fingerprint = module.AUTHORIZED_ACCOUNT_FINGERPRINT
    module._STATE.session_id = "live-session-01"
    return module


def command(bridge, command_type="SUBMIT_LIMIT", **overrides):
    client_order_id = "live-canary-001"
    payload = {
        "live_canary": True,
        "expected_qmt_session_id": bridge._STATE.session_id,
    }
    if command_type == "SUBMIT_LIMIT":
        payload.update(
            {
                "symbol": "00700.SGT",
                "side": "BUY",
                "quantity": 100,
                "limit_price": "1.00",
            }
        )
    else:
        payload["broker_order_id"] = "broker-live-001"
    payload.update(overrides)
    return {
        "command_type": command_type,
        "client_order_id": client_order_id,
        "broker_token": broker_token_for(
            bridge.AUTHORIZED_ACCOUNT_FINGERPRINT, client_order_id
        ),
        "payload": payload,
    }


def called_names(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    stack = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id in {"passorder", "cancel"}:
                found.append((node.func.id, stack[-1]))
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


def test_live_canary_artifact_has_exact_mutation_surface_and_identity():
    bridge = load_bridge()
    assert bridge.BRIDGE_BUILD == "p6-guojin-live-canary-3"
    assert bridge.EXECUTION_MODE == "LIVE_CANARY"
    assert bridge.TERMINAL_INSTANCE_ID == "guojin"
    assert bridge.SIMULATION_ONLY is False
    assert bridge.SIMULATION_MAX_SUBMIT_CALLS == 1
    assert bridge.SIMULATION_MAX_CANCEL_CALLS == 1
    assert called_names(BRIDGE) == [
        ("passorder", "_execute_order_command"),
        ("cancel", "_execute_order_command"),
    ]


def test_live_canary_submit_is_exactly_bounded(monkeypatch):
    bridge = load_bridge()
    calls = []
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)

    result = bridge._execute_order_command(command(bridge), Context())

    assert result == ("LIVE_CANARY_SUBMIT_CALL_RETURNED", True)
    assert calls[0][:7] == (23, 1101, "LIVE_ACCOUNT", "00700.SGT", 11, 1.0, 100)
    assert calls[0][7:10] == ("BIGQMT_LIVE_CANARY", 2, command(bridge)["broker_token"])
    with pytest.raises(bridge.CommandError, match="session limit"):
        bridge._execute_order_command(command(bridge), Context())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("live_canary", False),
        ("expected_qmt_session_id", "stale"),
        ("symbol", "000001.SZ"),
        ("side", "SELL"),
        ("quantity", 99),
        ("limit_price", "1.01"),
    ],
)
def test_live_canary_rejects_any_scope_expansion(monkeypatch, field, value):
    bridge = load_bridge()
    calls = []
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)
    candidate = command(bridge, **{field: value})
    with pytest.raises(bridge.CommandError):
        bridge._execute_order_command(candidate, Context())
    assert calls == []


def test_live_canary_fails_closed_when_instrument_preflight_is_missing(monkeypatch):
    bridge = load_bridge()
    calls = []
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)
    with pytest.raises(bridge.CommandError, match="instrument preflight"):
        bridge._execute_order_command(command(bridge), object())
    assert calls == []


def test_live_canary_fails_closed_on_instrument_identity_mismatch(monkeypatch):
    bridge = load_bridge()
    calls = []
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)

    class WrongContext:
        def get_instrumentdetail(self, _symbol):
            return {"ExchangeID": "HK", "InstrumentID": "00700"}

    with pytest.raises(bridge.CommandError, match="exchange mismatch"):
        bridge._execute_order_command(command(bridge), WrongContext())
    assert calls == []


def test_live_canary_runtime_probe_reports_all_market_routes():
    bridge = load_bridge()

    class ProbeContext:
        def get_instrument_detail(self, symbol):
            if symbol == "00700.SGT":
                return {
                    "ExchangeID": "SGT",
                    "ExchangeCode": "SGT",
                    "InstrumentID": "00700",
                    "InstrumentName": "Tencent",
                    "IsTrading": True,
                    "HSGTFlag": 1,
                }
            return {
                "ExchangeID": None,
                "ExchangeCode": None,
                "InstrumentID": None,
                "InstrumentName": None,
                "IsTrading": None,
                "HSGTFlag": None,
            }

    payload = bridge._runtime_instrument_probe(ProbeContext())
    assert [row["symbol"] for row in payload["candidates"]] == [
        "00700.HK",
        "00700.HGT",
        "00700.SGT",
    ]
    assert [row["observed"] for row in payload["candidates"]] == [False, False, True]
    assert payload["candidates"][2]["exchange_id"] == "SGT"


def test_live_canary_cancel_requires_exact_broker_id_and_token(monkeypatch):
    bridge = load_bridge()
    candidate = command(bridge, "CANCEL_ORDER")
    row = Obj()
    row.m_strOrderSysID = "broker-live-001"
    row.m_strRemark = candidate["broker_token"]
    calls = []
    monkeypatch.setattr(bridge, "get_trade_detail_data", lambda *_args: [row], raising=False)
    monkeypatch.setattr(bridge, "can_cancel_order", lambda *_args: True, raising=False)
    monkeypatch.setattr(bridge, "cancel", lambda *args: calls.append(args) or True, raising=False)

    assert bridge._execute_order_command(candidate, object()) == (
        "LIVE_CANARY_CANCEL_SIGNAL_SENT",
        True,
    )
    assert calls[0][:3] == ("broker-live-001", "LIVE_ACCOUNT", "STOCK")
