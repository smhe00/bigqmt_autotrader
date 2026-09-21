from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, Side
from bigqmt_autotrader.qmt.archive import DailySpoolArchiver
from bigqmt_autotrader.qmt.guojin_sim_oms import GuojinSimOmsRuntime
from bigqmt_autotrader.qmt.instances import QmtInstance
from bigqmt_autotrader.risk import (
    AccountRiskSnapshot,
    RiskPolicy,
    RiskSnapshot,
    RuntimeMode,
    SecurityRiskSnapshot,
    StrategyPolicy,
    StrategyRiskSnapshot,
    evaluate_risk,
)


FP = "sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702"
SESSION = "guojin-sim-execution-loop"


def instance(root):
    return QmtInstance(
        instance_id="guojin_sim", root=root, session_id=SESSION,
        account_fingerprint=FP, account_type="STOCK",
        bridge_build="p5-simulation-calibration-7", created_ms=1_800_000_000_000,
        execution_mode="SIMULATION_CALIBRATION", trading_enabled=True,
        live_submit=True, live_cancel=True, simulation_only=True,
    )


def intent(client_order_id="cid-sim-exec"):
    now = datetime.now(timezone.utc)
    return OrderIntent(
        client_order_id=client_order_id, strategy_id="sim-strategy",
        strategy_version="v1", account_fingerprint=FP, symbol="510300.SH",
        side=Side.BUY, quantity=100, limit_price=Decimal("1.00"),
        created_at=now, expires_at=now + timedelta(minutes=10),
        signal_id="sim-signal", reason_code="SIMULATION_TEST",
    )


def policy():
    return RiskPolicy(
        rule_version="p6-t004-test", expected_account_fingerprint=FP,
        permitted_execution_modes=frozenset({RuntimeMode.SIMULATION}),
        require_qmt_healthy=False, account_max_age_seconds=60,
        strategy_max_age_seconds=60, market_max_age_seconds=60,
        min_cash_buffer=Decimal("0"), fee_buffer_rate=Decimal("0"),
        max_account_gross_exposure=Decimal("1000000"), max_daily_loss_abs=Decimal("1000000"),
        max_daily_turnover=Decimal("1000000"), max_daily_orders=100,
        max_daily_cancels=100, max_order_notional=Decimal("1000000"),
        max_security_gross_exposure=Decimal("1000000"),
        max_price_deviation_rate=Decimal("0.5"),
        strategy=StrategyPolicy(
            strategy_id="sim-strategy", allowed_versions=frozenset({"v1"}),
            allowed_symbols=frozenset({"510300.SH"}), max_gross_exposure=Decimal("1000000"),
            max_daily_turnover=Decimal("1000000"), max_position_count=10,
        ),
    )


def snapshot(mode=RuntimeMode.SIMULATION):
    now = datetime.now(timezone.utc)
    return RiskSnapshot(
        mode=mode, database_healthy=True, oms_healthy=True, leader_held=True,
        reconciliation_complete=True, qmt_healthy=False, market_open=True,
        global_ambiguity_block=False, blocked_symbols=frozenset(),
        account=AccountRiskSnapshot(FP, Decimal("100000"), Decimal("0"), Decimal("0"),
                                    Decimal("0"), 0, 0, now),
        strategy=StrategyRiskSnapshot("sim-strategy", "v1", Decimal("0"), Decimal("0"),
                                      Decimal("0"), 0, now),
        security=SecurityRiskSnapshot("510300.SH", Decimal("0.01"), Decimal("0.50"),
                                      Decimal("1.50"), Decimal("1.00"), 100, 100, 1000,
                                      Decimal("0"), now),
    )


def _command_paths(root):
    return list((root / "commands").glob("*/*.json"))


def test_risk_reject_persists_zero_simulation_commands(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        result = runtime.execute_intent(intent(), snapshot(RuntimeMode.DISABLED), policy())
        assert result.status is OrderStatus.RISK_REJECTED
        assert result.command_id is None
        assert _command_paths(tmp_path) == []
    finally:
        runtime.close()


def test_submit_is_deterministic_and_repeated_execution_never_republishes(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        order = intent()
        first = runtime.execute_intent(order, snapshot(), policy())
        second = runtime.execute_intent(order, snapshot(), policy())
        assert first.command_id == second.command_id
        assert first.dispatched is True
        assert second.dispatched is False
        assert len(_command_paths(tmp_path)) == 1
        assert runtime.repository.get_status(FP, order.client_order_id) is OrderStatus.RECONCILING
    finally:
        runtime.close()


def test_planned_dispatch_recovers_only_when_exact_absence_is_provable(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        order = intent("cid-crash-before-publish")
        runtime.repository.create_intent(order)
        runtime.repository.record_risk_decision(
            FP, order.client_order_id,
            evaluate_risk(order, snapshot(), policy(), now=datetime.now(timezone.utc)).decision
        )
        runtime.mapper.register_order(client_order_id=order.client_order_id, symbol=order.symbol,
                                      quantity=order.quantity)
        runtime.repository.prepare_submit(FP, order.client_order_id)
        command = runtime._build_submit_command(order)
        runtime._persist_dispatch(command, broker_order_id=None)
        assert _command_paths(tmp_path) == []
        runtime.recover_dispatches()
        assert len(_command_paths(tmp_path)) == 1
        assert runtime.repository.get_status(FP, order.client_order_id) is OrderStatus.RECONCILING
    finally:
        runtime.close()


def test_cancel_is_exactly_once_and_terminal_cancel_is_noop(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        order = intent("cid-cancel")
        runtime.execute_intent(order, snapshot(), policy())
        token = runtime.mapper.register_order(client_order_id=order.client_order_id,
                                              symbol=order.symbol, quantity=order.quantity)
        from bigqmt_autotrader.qmt.protocol import QmtEvent
        event = QmtEvent.from_mapping({
            "protocol_version": "0.2", "session_id": SESSION, "sequence": 1,
            "timestamp_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "event_type": "order", "source": "callback", "account_fingerprint": FP,
            "account_type": "STOCK", "terminal_instance_id": "guojin_sim",
            "payload": {"symbol": order.symbol, "remark": token, "order_ref": "r1",
                        "broker_order_id": "9001", "status_code": 50,
                        "submit_status_code": 51, "original_quantity": 100,
                        "filled_quantity": 0, "remaining_quantity": 100},
        })
        runtime.ingest_broker_evidence(runtime.mapper(event))
        first = runtime.cancel_intent(order.client_order_id)
        second = runtime.cancel_intent(order.client_order_id)
        assert first.dispatched is True
        assert second.dispatched is False
        assert len(_command_paths(tmp_path)) == 2
        runtime.repository.transition_order(FP, order.client_order_id, OrderStatus.CANCELLED,
                                            event_type="test-terminal")
        terminal = runtime.cancel_intent(order.client_order_id)
        assert terminal.terminal_noop is True
        assert len(_command_paths(tmp_path)) == 2
    finally:
        runtime.close()


def _dispatch_rows(runtime, client_order_id):
    return runtime.conn.execute(
        """SELECT * FROM qmt_execution_dispatches
           WHERE account_fingerprint=? AND client_order_id=?
           ORDER BY command_type""",
        (FP, client_order_id),
    ).fetchall()


def _ack(runtime, order, *, broker_order_id="9001", sequence=1):
    token = runtime.mapper.register_order(
        client_order_id=order.client_order_id,
        symbol=order.symbol,
        quantity=order.quantity,
    )
    from bigqmt_autotrader.qmt.protocol import QmtEvent
    event = QmtEvent.from_mapping({
        "protocol_version": "0.2", "session_id": SESSION, "sequence": sequence,
        "timestamp_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "event_type": "order", "source": "callback", "account_fingerprint": FP,
        "account_type": "STOCK", "terminal_instance_id": "guojin_sim",
        "payload": {"symbol": order.symbol, "remark": token, "order_ref": "r1",
                    "broker_order_id": broker_order_id, "status_code": 50,
                    "submit_status_code": 51, "original_quantity": 100,
                    "filled_quantity": 0, "remaining_quantity": 100},
    })
    runtime.ingest_broker_evidence(runtime.mapper(event))


def test_submit_reservation_and_plan_rollback_together_on_precommit_failure(tmp_path, monkeypatch):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    order = intent("cid-submit-atomic-rollback")
    try:
        original = runtime._persist_dispatch_in_tx

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("fault after dispatch insert before commit")

        monkeypatch.setattr(runtime, "_persist_dispatch_in_tx", fail)
        with pytest.raises(RuntimeError, match="fault after dispatch"):
            runtime.execute_intent(order, snapshot(), policy())
        row = runtime.repository.get_order_row(FP, order.client_order_id)
        assert OrderStatus(row["status"]) is OrderStatus.RISK_ACCEPTED
        assert row["submit_call_started"] == 0
        assert _dispatch_rows(runtime, order.client_order_id) == []
        assert _command_paths(tmp_path) == []
    finally:
        runtime.close()


def test_submit_atomic_commit_survives_crash_before_publish_and_recovers_once(tmp_path, monkeypatch):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    order = intent("cid-submit-after-commit")
    try:
        monkeypatch.setattr(
            runtime, "_recover_dispatch",
            lambda row: (_ for _ in ()).throw(RuntimeError("crash after commit")),
        )
        with pytest.raises(RuntimeError, match="crash after commit"):
            runtime.execute_intent(order, snapshot(), policy())
        row = runtime.repository.get_order_row(FP, order.client_order_id)
        assert OrderStatus(row["status"]) is OrderStatus.SUBMITTING
        dispatch = _dispatch_rows(runtime, order.client_order_id)
        assert len(dispatch) == 1 and dispatch[0]["dispatch_state"] == "PLANNED"
        assert _command_paths(tmp_path) == []
    finally:
        runtime.close()

    restarted = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        assert len(_command_paths(tmp_path)) == 1
        assert restarted.repository.get_status(FP, order.client_order_id) is OrderStatus.RECONCILING
    finally:
        restarted.close()


def test_startup_sweeps_fault_injected_submit_reservation_without_dispatch(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    order = intent("cid-orphan-submit")
    try:
        runtime.repository.create_intent(order)
        runtime.repository.record_risk_decision(
            FP, order.client_order_id,
            evaluate_risk(order, snapshot(), policy(), now=datetime.now(timezone.utc)).decision,
        )
        runtime.repository.prepare_submit(FP, order.client_order_id)
    finally:
        runtime.close()

    restarted = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        assert restarted.repository.get_status(FP, order.client_order_id) is OrderStatus.MANUAL_REVIEW
        assert _command_paths(tmp_path) == []
    finally:
        restarted.close()


def test_cancel_reservation_and_plan_rollback_together_on_precommit_failure(tmp_path, monkeypatch):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    order = intent("cid-cancel-atomic-rollback")
    try:
        runtime.execute_intent(order, snapshot(), policy())
        _ack(runtime, order)
        original = runtime._persist_dispatch_in_tx

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("fault after cancel dispatch insert before commit")

        monkeypatch.setattr(runtime, "_persist_dispatch_in_tx", fail)
        with pytest.raises(RuntimeError, match="fault after cancel"):
            runtime.cancel_intent(order.client_order_id)
        row = runtime.repository.get_order_row(FP, order.client_order_id)
        assert OrderStatus(row["status"]) is OrderStatus.ACKNOWLEDGED
        assert row["cancel_call_started"] == 0
        assert len(_dispatch_rows(runtime, order.client_order_id)) == 1
    finally:
        runtime.close()


def test_cancel_atomic_commit_survives_crash_before_publish_and_recovers_once(tmp_path, monkeypatch):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    order = intent("cid-cancel-after-commit")
    try:
        runtime.execute_intent(order, snapshot(), policy())
        _ack(runtime, order)
        original = runtime._recover_dispatch
        monkeypatch.setattr(
            runtime, "_recover_dispatch",
            lambda row: (
                (_ for _ in ()).throw(RuntimeError("crash after cancel commit"))
                if row["command_type"] == "CANCEL_ORDER" else original(row)
            ),
        )
        with pytest.raises(RuntimeError, match="crash after cancel commit"):
            runtime.cancel_intent(order.client_order_id)
        row = runtime.repository.get_order_row(FP, order.client_order_id)
        assert OrderStatus(row["status"]) is OrderStatus.CANCEL_PENDING
        cancel_rows = [
            r for r in _dispatch_rows(runtime, order.client_order_id)
            if r["command_type"] == "CANCEL_ORDER"
        ]
        assert len(cancel_rows) == 1 and cancel_rows[0]["dispatch_state"] == "PLANNED"
    finally:
        runtime.close()

    restarted = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        cancel_paths = [
            p for p in _command_paths(tmp_path)
            if p.name.startswith("simoms-")
        ]
        assert len(cancel_paths) == 2
        assert restarted.repository.get_status(FP, order.client_order_id) is OrderStatus.RECONCILING
    finally:
        restarted.close()


def test_startup_sweeps_fault_injected_cancel_reservation_without_dispatch(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    order = intent("cid-orphan-cancel")
    try:
        runtime.execute_intent(order, snapshot(), policy())
        _ack(runtime, order)
        runtime.repository.prepare_cancel(FP, order.client_order_id)
    finally:
        runtime.close()

    restarted = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        row = restarted.repository.get_order_row(FP, order.client_order_id)
        assert OrderStatus(row["status"]) is OrderStatus.MANUAL_REVIEW
        assert row["cancel_outcome_resolved"] == 1
    finally:
        restarted.close()


def test_expired_planned_submit_never_publishes_and_converges_manual_review(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    order = intent("cid-expired-submit")
    try:
        runtime.repository.create_intent(order)
        runtime.repository.record_risk_decision(
            FP, order.client_order_id,
            evaluate_risk(order, snapshot(), policy(), now=datetime.now(timezone.utc)).decision,
        )
        command = replace(runtime._build_submit_command(order), expires_ms=1)
        row = runtime._reserve_and_persist_dispatch(
            command, broker_order_id=None, cancel=False
        )
        runtime._recover_dispatch(row)
        assert runtime.repository.get_status(FP, order.client_order_id) is OrderStatus.MANUAL_REVIEW
        assert _command_paths(tmp_path) == []
    finally:
        runtime.close()


def test_expired_planned_cancel_never_publishes_and_converges_manual_review(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    order = intent("cid-expired-cancel")
    try:
        runtime.execute_intent(order, snapshot(), policy())
        _ack(runtime, order)
        command = replace(runtime._build_cancel_command(order.client_order_id, "9001"), expires_ms=1)
        row = runtime._reserve_and_persist_dispatch(
            command, broker_order_id="9001", cancel=True
        )
        runtime._recover_dispatch(row)
        dbrow = runtime.repository.get_order_row(FP, order.client_order_id)
        assert OrderStatus(dbrow["status"]) is OrderStatus.MANUAL_REVIEW
        assert dbrow["cancel_outcome_resolved"] == 1
    finally:
        runtime.close()


def test_event_archiver_never_treats_command_history_as_archivable_event_spool(tmp_path):
    command_history = tmp_path / "commands" / "processed" / "simoms-history.json"
    command_history.parent.mkdir(parents=True)
    command_history.write_text("{}", encoding="utf-8")
    archiver = DailySpoolArchiver(spool_root=tmp_path)
    assert archiver.discover_processed_days() == ()
    assert command_history.exists()
