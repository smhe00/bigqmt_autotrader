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
        if symbol == "204001.SH":
            return {"ExchangeID": "SH", "InstrumentID": "204001", "IsTrading": True}
        if symbol == "511880.SH":
            return {"ExchangeID": "SH", "InstrumentID": "511880", "IsTrading": True}
        assert symbol == "00700.HGT"
        return {
            "ExchangeID": "HK",
            "InstrumentID": "00700",
            "IsTrading": True,
            "HSGTFlag": 5,
        }


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_v05_guojin", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._STATE.account_id = "LIVE_ACCOUNT"
    module._STATE.account_type = "STOCK"
    module._STATE.account_fingerprint = module.AUTHORIZED_ACCOUNT_FINGERPRINT
    module._STATE.session_id = "live-session-01"
    module._STATE.detected_account_types.add("SHENGANGTONG")
    module._STATE.detected_account_types.add("HUGANGTONG")
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
                "symbol": "00700.HGT",
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
    assert bridge.BRIDGE_BUILD == "p6-guojin-live-canary-7"
    assert bridge.EXECUTION_MODE == "LIVE_CANARY"
    assert bridge.TERMINAL_INSTANCE_ID == "guojin"
    assert bridge.SIMULATION_ONLY is False
    assert bridge.SIMULATION_MAX_SUBMIT_CALLS == 1
    assert bridge.SIMULATION_MAX_CANCEL_CALLS == 1
    assert bridge._LIVE_CANARY_MUTATION_SYMBOLS == ("00700.HGT",)
    assert bridge._LIVE_CANARY_AUTHORIZED_SIDE == "BUY"
    assert bridge._LIVE_CANARY_AUTHORIZED_QUANTITY == 100
    assert bridge._LIVE_CANARY_AUTHORIZED_LIMIT_PRICE == 1.0
    assert called_names(BRIDGE) == [
        ("passorder", "_execute_order_command"),
        ("cancel", "_execute_order_command"),
    ]


def _arm_hgt_submit(bridge, monkeypatch):
    calls = []
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)
    monkeypatch.setattr(bridge, "_live_canary_trade_window_open", lambda: True)
    account = Obj()
    account.m_dAvailable = 2168.79
    monkeypatch.setattr(
        bridge, "get_trade_detail_data", lambda *_args: [account], raising=False
    )
    return calls


def test_live_canary_submit_is_exactly_bounded(monkeypatch):
    bridge = load_bridge()
    calls = _arm_hgt_submit(bridge, monkeypatch)

    result = bridge._execute_order_command(command(bridge), Context())

    assert result == ("LIVE_CANARY_SUBMIT_CALL_RETURNED", True)
    # op_type 23 = BUY; fixed non-marketable 1.00 HKD route price; size 100.
    assert calls[0][:7] == (23, 1101, "LIVE_ACCOUNT", "00700.HGT", 11, 1.0, 100)
    assert calls[0][7:10] == ("BIGQMT_LIVE_CANARY", 2, command(bridge)["broker_token"])
    # P6-T001 fuse = 1: a second submit is rejected by the session quota,
    # not merely by per-case bookkeeping.
    with pytest.raises(bridge.CommandError, match="submit session limit reached"):
        bridge._execute_order_command(command(bridge), Context())
    assert len(calls) == 1


@pytest.mark.parametrize("symbol", ["204001.SH", "511880.SH"])
def test_live_canary_rejects_historical_and_future_symbols(monkeypatch, symbol):
    bridge = load_bridge()
    calls = _arm_hgt_submit(bridge, monkeypatch)
    side = "SELL" if symbol == "204001.SH" else "BUY"
    quantity = 10 if symbol == "204001.SH" else 100
    price = "100.000" if symbol == "204001.SH" else "100.805"
    candidate = command(
        bridge, symbol=symbol, side=side, quantity=quantity, limit_price=price
    )
    with pytest.raises(bridge.CommandError, match="exactly one submit case"):
        bridge._execute_order_command(candidate, Context())
    assert calls == []


def test_live_canary_rejects_hgt_with_any_other_case_shape(monkeypatch):
    bridge = load_bridge()
    calls = _arm_hgt_submit(bridge, monkeypatch)
    for overrides in (
        {"side": "SELL"},
        {"quantity": 200},
        {"limit_price": "1.01"},
        {"limit_price": "0.99"},
    ):
        with pytest.raises(bridge.CommandError, match="exactly one submit case"):
            bridge._execute_order_command(command(bridge, **overrides), Context())
    assert calls == []


def test_live_canary_halted_session_rejects_every_later_mutation(monkeypatch):
    bridge = load_bridge()
    bridge._STATE.live_canary_halted = True
    calls = []
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)
    with pytest.raises(bridge.CommandError, match="session halted"):
        bridge._execute_order_command(command(bridge), Context())
    assert calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("live_canary", False),
        ("expected_qmt_session_id", "stale"),
        ("symbol", "000001.SZ"),
        ("symbol", "204001.SH"),
        ("symbol", "511880.SH"),
        ("side", "SELL"),
        ("quantity", 11),
        ("quantity", 1000),
        ("limit_price", "1.01"),
        ("limit_price", "0.99"),
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
    monkeypatch.setattr(bridge, "_live_canary_trade_window_open", lambda: True)
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)
    with pytest.raises(bridge.CommandError, match="instrument preflight"):
        bridge._execute_order_command(command(bridge), object())
    assert calls == []


def test_live_canary_fails_closed_on_instrument_identity_mismatch(monkeypatch):
    bridge = load_bridge()
    calls = []
    monkeypatch.setattr(bridge, "_live_canary_trade_window_open", lambda: True)
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)

    class WrongContext:
        def get_instrumentdetail(self, _symbol):
            return {"ExchangeID": "HK", "InstrumentID": "00700"}

    with pytest.raises(bridge.CommandError, match="identity mismatch"):
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
        "204001.SH", "511880.SH", "00700.HK", "00700.HGT", "00700.SGT",
    ]
    assert [row["observed"] for row in payload["candidates"]] == [False, False, False, False, True]
    assert payload["candidates"][4]["exchange_id"] == "SGT"


def test_live_canary_read_only_subscription_and_delayed_probe(monkeypatch):
    bridge = load_bridge()
    subscribed = []
    callbacks = {}
    timers = []
    emitted = []

    class ProbeContext:
        def subscribe_quote(self, symbol, period, dividend_type="none", callback=None):
            subscribed.append((symbol, period, dividend_type))
            callbacks[symbol] = callback
            return len(subscribed)

        def run_time(self, callback, period, start):
            timers.append((callback, period, start))

        def get_instrument_detail(self, _symbol):
            return {}

    monkeypatch.setattr(bridge, "_enqueue", lambda *args: emitted.append(args))
    monkeypatch.setattr(bridge, "_safe_log", lambda *_args: None)
    monkeypatch.setattr(bridge, "flush_transport", lambda: None)
    context = ProbeContext()

    result = bridge._runtime_instrument_subscribe(context)
    assert subscribed == [
        ("204001.SH", "tick", "none"),
        ("511880.SH", "tick", "none"),
        ("00700.HK", "tick", "none"),
        ("00700.HGT", "tick", "none"),
        ("00700.SGT", "tick", "none"),
    ]
    assert all(row["accepted"] for row in result["candidates"])
    assert all(row["callback_registered"] for row in result["candidates"])
    assert result["tick_evidence_required"] is True
    assert result["probe_timer_registered"] is True
    assert timers == [("instrument_probe_tick", "1nSecond", bridge.TIMER_START)]

    class FakeILoc:
        def __getitem__(self, _index):
            return {
                "stockCode": "00700.HGT",
                "lastPrice": 400.0,
                "time": 1_789_000_000_000,
                "volume": 12345,
            }

    class FakeFrame:
        index = ["20260918093000"]
        iloc = FakeILoc()

    callbacks["00700.HGT"]({"00700.SGT": {"lastPrice": 400.0}})
    mismatch_events = [
        item for item in emitted if item[0] == "instrument_tick_capabilities"
    ]
    mismatch_hgt = [
        row
        for row in mismatch_events[-1][2]["candidates"]
        if row["symbol"] == "00700.HGT"
    ][0]
    assert mismatch_hgt["tick_observed"] is False
    assert mismatch_hgt["evidence"]["exact_symbol"] is False

    callbacks["00700.HGT"]({"00700.HGT": FakeFrame()})
    tick_events = [item for item in emitted if item[0] == "instrument_tick_capabilities"]
    assert tick_events
    hgt = [
        row
        for row in tick_events[-1][2]["candidates"]
        if row["symbol"] == "00700.HGT"
    ][0]
    assert hgt["tick_observed"] is True
    assert hgt["callback_count"] == 2
    assert hgt["evidence"]["requested_symbol"] == "00700.HGT"
    assert hgt["evidence"]["reported_symbol"] == "00700.HGT"
    assert hgt["evidence"]["exact_symbol"] is True
    assert hgt["evidence"]["raw_symbol"] == "00700.HGT"
    assert hgt["evidence"]["tick_index"] == "20260918093000"
    assert hgt["evidence"]["last_price"] == "400.0"

    for _ in range(10):
        bridge.instrument_probe_tick(context)
    final_tick_events = [
        item
        for item in emitted
        if item[0] == "instrument_tick_capabilities" and item[2]["final"] is True
    ]
    assert final_tick_events
    assert final_tick_events[-1][2]["observed_count"] == 1
    assert bridge._STATE.simulation_submit_calls == 0
    assert bridge._STATE.simulation_cancel_calls == 0


def test_live_canary_subscription_preserves_synchronous_tick(monkeypatch):
    bridge = load_bridge()

    class ImmediateContext:
        def subscribe_quote(self, symbol, _period, _dividend_type="none", callback=None):
            callback({symbol: {"stockCode": symbol, "lastPrice": 100.0}})
            return 9

        def run_time(self, _callback, _period, _start):
            return None

    monkeypatch.setattr(bridge, "_enqueue", lambda *_args: None)
    monkeypatch.setattr(bridge, "_safe_log", lambda *_args: None)
    monkeypatch.setattr(bridge, "flush_transport", lambda: None)
    bridge._runtime_instrument_subscribe(ImmediateContext())
    assert all(
        row["tick_observed"] is True
        for row in bridge._tick_capabilities_payload()["candidates"]
    )


def test_live_canary_full_tick_fallback_proves_exact_symbols(monkeypatch):
    bridge = load_bridge()
    bridge._STATE.instrument_tick_records = {}

    class FullTickContext:
        def get_full_tick(self, symbols):
            symbol = symbols[0]
            return {
                symbol: {
                    "stockCode": symbol,
                    "lastPrice": 100.0,
                    "time": 1_789_000_000_000,
                }
            }

    monkeypatch.setattr(bridge, "_enqueue", lambda *_args: None)
    monkeypatch.setattr(bridge, "_safe_log", lambda *_args: None)
    monkeypatch.setattr(bridge, "flush_transport", lambda: None)
    result = bridge._runtime_full_tick_probe(FullTickContext())
    assert result == {"method": "get_full_tick", "attempted": 5, "observed": 5}
    assert all(
        row["tick_observed"] is True
        and row["evidence_source"] == "full_tick_poll"
        and row["evidence"]["reported_symbol"] == row["symbol"]
        for row in bridge._tick_capabilities_payload()["candidates"]
    )

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
