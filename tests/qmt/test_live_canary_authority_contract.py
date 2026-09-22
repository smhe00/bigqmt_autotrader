"""Permanent LIVE_CANARY authority regression gate (P6-T001).

"Only one passorder call site" does NOT imply "only one authorized case".
These tests pin the authorization SEMANTICS of the production Guojin live
canary: exactly one host-side case, exactly one generated-bridge mutation
symbol, one-shot fuses, zero generic/galaxy surface, unchanged simulation
authority, generator/artifact consistency, and doc/host/artifact agreement.

They never execute a broker API: the generated bridge is loaded as a plain
module and passorder/cancel are monkeypatched away.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from bigqmt_autotrader.qmt import live_canary_probe as host_probe
from bigqmt_autotrader.qmt.instances import QmtInstance


ROOT = Path(__file__).resolve().parents[2]
QMT_SIDE = ROOT / "qmt_side"
TOOLS = ROOT / "tools"
GUOJIN = QMT_SIDE / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py"
GUOJIN_SIM = QMT_SIDE / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py"
GENERIC = QMT_SIDE / "BIGQMT_EXECUTION_BRIDGE_V05.py"
GALAXY = QMT_SIDE / "BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py"

BUILD = "p6-guojin-live-canary-7"
MUTATION_CALLS = {
    "passorder",
    "cancel",
    "order_lots",
    "algo_passorder",
    "smart_algo_passorder",
    "cancel_task",
    "pause_task",
    "resume_task",
}


# ---------------------------------------------------------------------------
# generated artifact loading
# ---------------------------------------------------------------------------

def load_artifact(path: Path):
    spec = importlib.util.spec_from_file_location("authority_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bridge():
    module = load_artifact(GUOJIN)
    module._STATE.account_id = "LIVE_ACCOUNT"
    module._STATE.account_type = "STOCK"
    module._STATE.account_fingerprint = module.AUTHORIZED_ACCOUNT_FINGERPRINT
    module._STATE.session_id = "authority-session"
    module._STATE.detected_account_types.add("HUGANGTONG")
    return module


# ---------------------------------------------------------------------------
# 1-3. Host publisher authority
# ---------------------------------------------------------------------------

def _host_instance(tmp_path):
    return QmtInstance(
        instance_id="guojin",
        root=tmp_path,
        session_id="live-session-01",
        account_fingerprint=host_probe.ACCOUNT_FINGERPRINT,
        account_type="STOCK",
        bridge_build=host_probe.BRIDGE_BUILD,
        created_ms=1_700_000_000_000,
        execution_mode="LIVE_CANARY",
        trading_enabled=True,
        live_submit=True,
        live_cancel=True,
        simulation_only=False,
    )


def _host_submit(tmp_path, monkeypatch, **case):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: _host_instance(tmp_path),
    )
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._live_canary_submit_window_open",
        lambda: True,
    )
    args = ["--spool-dir", str(tmp_path),
            "--confirm", host_probe.CONFIRMATION, "submit",
            "--client-order-id", "authority-cid"]
    for key, value in case.items():
        args.extend(["--" + key.replace("_", "-"), str(value)])
    return host_probe.main(args)


def test_invariant_1_host_publisher_accepts_exactly_the_single_hgt_case(
    tmp_path, monkeypatch
):
    assert host_probe.BRIDGE_BUILD == BUILD
    assert _host_submit(
        tmp_path, monkeypatch,
        symbol="00700.HGT", side="BUY", quantity=100, limit_price="1.00",
    ) == 0
    commands = list((tmp_path / "commands" / "inbox").glob("*.json"))
    assert len(commands) == 1


@pytest.mark.parametrize(
    "case",
    [
        # 2. GC001 historical calibration must never be resubmitted.
        dict(symbol="204001.SH", side="SELL", quantity=10, limit_price="100.000"),
        # 3. 511880 is read-only pending its own independent Gate.
        dict(symbol="511880.SH", side="BUY", quantity=100, limit_price="100.805"),
        # Any other HGT case shape is rejected too.
        dict(symbol="00700.HGT", side="SELL", quantity=100, limit_price="1.00"),
        dict(symbol="00700.HGT", side="BUY", quantity=200, limit_price="1.00"),
        dict(symbol="00700.HGT", side="BUY", quantity=100, limit_price="1.01"),
    ],
)
def test_invariants_2_3_host_rejects_gc001_511880_and_shape_drift_before_spool(
    tmp_path, monkeypatch, case
):
    with pytest.raises(SystemExit, match="exactly one submit case"):
        _host_submit(tmp_path, monkeypatch, **case)
    inbox = tmp_path / "commands" / "inbox"
    assert not inbox.exists() or list(inbox.glob("*.json")) == []


# ---------------------------------------------------------------------------
# 4-6. Generated bridge authority and fuses
# ---------------------------------------------------------------------------

def test_invariant_4_generated_mutation_whitelist_is_single_symbol(bridge):
    assert bridge._LIVE_CANARY_MUTATION_SYMBOLS == ("00700.HGT",)
    assert bridge._live_canary_symbol("00700.HGT") == "00700.HGT"
    for denied in ("204001.SH", "511880.SH", "00700.HK", "00700.SGT", "000001.SZ"):
        assert bridge._live_canary_symbol(denied) is None


def test_invariants_5_6_generated_submit_and_cancel_fuses_are_one(bridge):
    assert bridge.SIMULATION_MAX_SUBMIT_CALLS == 1
    assert bridge.SIMULATION_MAX_CANCEL_CALLS == 1
    assert bridge.BRIDGE_BUILD == BUILD
    assert bridge.EXECUTION_MODE == "LIVE_CANARY"
    assert bridge.TRADING_ENABLED is True
    assert bridge.SIMULATION_ONLY is False


def test_generated_executor_rejects_gc001_and_511880_without_broker_call(
    bridge, monkeypatch
):
    calls = []
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)
    monkeypatch.setattr(bridge, "_live_canary_trade_window_open", lambda: True)
    from bigqmt_autotrader.qmt.commands import broker_token_for

    for symbol, side, quantity, price in (
        ("204001.SH", "SELL", 10, "100.000"),
        ("511880.SH", "BUY", 100, "100.805"),
    ):
        command = {
            "command_type": "SUBMIT_LIMIT",
            "client_order_id": "authority-" + symbol,
            "broker_token": broker_token_for(
                bridge.AUTHORIZED_ACCOUNT_FINGERPRINT, "authority-" + symbol
            ),
            "payload": {
                "live_canary": True,
                "expected_qmt_session_id": bridge._STATE.session_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "limit_price": price,
            },
        }
        with pytest.raises(bridge.CommandError, match="exactly one submit case"):
            bridge._execute_order_command(command, object())
    assert calls == []
    assert bridge._STATE.simulation_submit_calls == 0


def test_generated_executor_blocks_second_submit_via_fuse(bridge, monkeypatch):
    calls = []
    monkeypatch.setattr(bridge, "passorder", lambda *args: calls.append(args), raising=False)
    monkeypatch.setattr(bridge, "_live_canary_trade_window_open", lambda: True)

    class Ctx:
        def get_instrument_detail(self, symbol):
            assert symbol == "00700.HGT"
            return {"ExchangeID": "HK", "InstrumentID": "00700", "HSGTFlag": 5}

        def get_instrumentdetail(self, symbol):
            return self.get_instrument_detail(symbol)

    account = type("Account", (), {"m_dAvailable": 2168.79})()
    monkeypatch.setattr(
        bridge, "get_trade_detail_data", lambda *_args: [account], raising=False
    )
    from bigqmt_autotrader.qmt.commands import broker_token_for

    def command(serial):
        cid = "authority-hgt-" + str(serial)
        return {
            "command_type": "SUBMIT_LIMIT",
            "client_order_id": cid,
            "broker_token": broker_token_for(bridge.AUTHORIZED_ACCOUNT_FINGERPRINT, cid),
            "payload": {
                "live_canary": True,
                "expected_qmt_session_id": bridge._STATE.session_id,
                "symbol": "00700.HGT",
                "side": "BUY",
                "quantity": 100,
                "limit_price": "1.00",
            },
        }

    assert bridge._execute_order_command(command(1), Ctx())[0] == (
        "LIVE_CANARY_SUBMIT_CALL_RETURNED"
    )
    with pytest.raises(bridge.CommandError, match="submit session limit reached"):
        bridge._execute_order_command(command(2), Ctx())
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# 7. Generic / Galaxy stay mutation-free at the source level
# ---------------------------------------------------------------------------

def _mutation_call_sites(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id in MUTATION_CALLS:
                found.append(node.func.id)
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


def test_invariant_7_generic_and_galaxy_have_zero_mutation_surface():
    generic = load_artifact(GENERIC)
    galaxy = load_artifact(GALAXY)
    for module in (generic, galaxy):
        assert module.TRADING_ENABLED is False
        assert module.LIVE_SUBMIT_ENABLED is False
        assert module.LIVE_CANCEL_ENABLED is False
        assert getattr(module, "SIMULATION_ONLY", False) is False
    assert _mutation_call_sites(GENERIC) == []
    assert _mutation_call_sites(GALAXY) == []


# ---------------------------------------------------------------------------
# 8. Simulation calibration authority is untouched by this task
# ---------------------------------------------------------------------------

def test_invariant_8_guojin_sim_authority_is_unchanged():
    sim = load_artifact(GUOJIN_SIM)
    assert sim.BRIDGE_BUILD == "p5-simulation-calibration-8"
    assert sim.EXECUTION_MODE == "SIMULATION_CALIBRATION"
    assert sim.TERMINAL_INSTANCE_ID == "guojin_sim"
    assert sim.SIMULATION_ONLY is True
    assert sim.TRADING_ENABLED is True
    assert sim.SIMULATION_MAX_ORDER_QUANTITY == 100
    assert sim.SIMULATION_MAX_SUBMIT_CALLS == 2000
    assert sim.SIMULATION_MAX_CANCEL_CALLS == 2000
    # The live-only single-case authority constants must not leak into sim.
    assert not hasattr(sim, "_LIVE_CANARY_MUTATION_SYMBOLS")
    assert not hasattr(sim, "_LIVE_CANARY_AUTHORIZED_SIDE")


# ---------------------------------------------------------------------------
# 9. Generator/artifact consistency
# ---------------------------------------------------------------------------

def test_invariant_9_deployment_generator_is_in_sync():
    result = subprocess.run(
        [sys.executable, str(TOOLS / "build_qmt_deployments.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# 10. docs / Host / generated artifact describe the same build and case
# ---------------------------------------------------------------------------

def test_invariant_10_docs_host_and_artifact_agree_on_build_and_case():
    guojin = load_artifact(GUOJIN)
    assert host_probe.BRIDGE_BUILD == guojin.BRIDGE_BUILD == BUILD

    current_status_docs = {
        "README.md": ROOT / "README.md",
        "PROJECT_OVERVIEW_ZH.md": ROOT / "docs" / "PROJECT_OVERVIEW_ZH.md",
        "PROJECT_STATUS.md": ROOT / "docs" / "PROJECT_STATUS.md",
        "FORMAL_VERIFICATION.md": ROOT / "docs" / "FORMAL_VERIFICATION.md",
    }
    for label, path in current_status_docs.items():
        text = path.read_text(encoding="utf-8")
        assert BUILD in text, f"{label} does not record {BUILD}"
        assert "canary-6" not in text, f"{label} still describes the retired build-6"

    # The P6 Gate is an audit trail: it may retain build-6 historical evidence,
    # but its current authority section must name build-7 and its operational
    # instructions must no longer tell an operator to run the GC001 -> Tencent
    # multi-case sequence or a 511880 submit in this build.
    gate_path = ROOT / "docs" / "P6_GUOJIN_LIVE_CANARY_GATE_20260918_ZH.md"
    gate = gate_path.read_text(encoding="utf-8")
    assert BUILD in gate
    assert "00700.HGT BUY 100 @ 1.00 HKD" in gate
    assert "GC001" in gate and "no longer authorized" in gate
    assert "GC001 → reconciliation → 腾讯" not in gate
    assert "submit/cancel fuse = 1/1" in gate or "submit/cancel fuse    = 1/1" in gate


# ---------------------------------------------------------------------------
# Tick freshness primitive (task section 4): fail-closed, broker time rules
# ---------------------------------------------------------------------------

FRESH_NOW = 1_789_000_000_000


def _tick_record(symbol="511880.SH", **evidence_overrides):
    evidence = {
        "exact_symbol": True,
        "reported_symbol": symbol,
        "last_price": "100.805",
        "tick_time": FRESH_NOW - 5_000,
    }
    evidence.update(evidence_overrides)
    return {
        "symbol": symbol,
        "tick_observed": True,
        "last_callback_ms": FRESH_NOW,
        "evidence": evidence,
    }


def test_fresh_exact_symbol_tick_is_accepted(bridge):
    bridge._STATE.instrument_tick_records = {"511880.SH": _tick_record()}
    assert bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW) == 100.805


def test_seconds_epoch_tick_time_is_normalized_and_accepted(bridge):
    bridge._STATE.instrument_tick_records = {
        "511880.SH": _tick_record(tick_time=(FRESH_NOW - 5_000) // 1000)
    }
    assert bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW) == 100.805


def test_stale_local_observation_is_rejected_even_if_callback_was_recent(bridge):
    # A just-now get_full_tick call must not launder an old broker quote:
    # last_callback_ms is current but the broker tick is 30 s stale.
    bridge._STATE.instrument_tick_records = {
        "511880.SH": _tick_record(tick_time=FRESH_NOW - 30_000)
    }
    with pytest.raises(bridge.CommandError, match="stale"):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


def test_previous_trading_day_tick_is_rejected(bridge):
    bridge._STATE.instrument_tick_records = {
        "511880.SH": _tick_record(tick_time=FRESH_NOW - 86_400_000)
    }
    with pytest.raises(bridge.CommandError, match="stale"):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


def test_tick_symbol_mismatch_is_rejected(bridge):
    bridge._STATE.instrument_tick_records = {
        "511880.SH": _tick_record(reported_symbol="00700.HGT")
    }
    with pytest.raises(bridge.CommandError, match="symbol mismatch"):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


@pytest.mark.parametrize("bad_time", [None, "", "not-a-timestamp", 0, -1])
def test_missing_or_invalid_broker_tick_time_fails_closed(bridge, bad_time):
    bridge._STATE.instrument_tick_records = {
        "511880.SH": _tick_record(tick_time=bad_time)
    }
    with pytest.raises(bridge.CommandError, match="broker tick time unavailable"):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


def test_positive_price_but_stale_tick_is_rejected(bridge):
    bridge._STATE.instrument_tick_records = {
        "511880.SH": _tick_record(last_price="101.0", tick_time=FRESH_NOW - 60_000)
    }
    with pytest.raises(bridge.CommandError, match="stale"):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


def test_future_broker_tick_is_rejected_as_clock_skew(bridge):
    bridge._STATE.instrument_tick_records = {
        "511880.SH": _tick_record(tick_time=FRESH_NOW + 60_000)
    }
    with pytest.raises(bridge.CommandError, match="future"):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


@pytest.mark.parametrize("bad_price", [None, "", "0", "-1.0", "not-a-price"])
def test_invalid_price_fails_closed(bridge, bad_price):
    bridge._STATE.instrument_tick_records = {
        "511880.SH": _tick_record(last_price=bad_price)
    }
    with pytest.raises(bridge.CommandError):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


def test_missing_observation_fails_closed(bridge):
    bridge._STATE.instrument_tick_records = {}
    with pytest.raises(bridge.CommandError, match="evidence unavailable"):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


def test_exact_symbol_identity_remains_required_for_freshness(bridge):
    record = _tick_record()
    record["evidence"]["exact_symbol"] = False
    bridge._STATE.instrument_tick_records = {"511880.SH": record}
    with pytest.raises(bridge.CommandError, match="evidence invalid"):
        bridge._live_canary_fresh_tick_price("511880.SH", now_ms=FRESH_NOW)


def test_freshness_constant_is_fifteen_seconds(bridge):
    assert bridge._LIVE_CANARY_TICK_FRESHNESS_MS == 15_000
