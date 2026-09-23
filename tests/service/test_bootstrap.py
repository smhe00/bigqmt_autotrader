from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.oms import (
    SUPPORTED_SCHEMA_VERSION,
    connect_database,
    initialize_database,
)
from bigqmt_autotrader.risk import RiskPolicy, RuntimeMode, StrategyPolicy
from bigqmt_autotrader.service import (
    DeploymentMismatch,
    ObservedDeployment,
    ReleaseManifest,
    StrategyHealthRequirement,
    bootstrap_runtime_services,
    canonical_config_digest,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=TZ)
FP = "sha256:" + "a" * 64
GIT_SHA = "b" * 40


def policy():
    return RiskPolicy(
        rule_version="bootstrap-v1",
        expected_account_fingerprint=FP,
        permitted_execution_modes=frozenset({RuntimeMode.SIMULATION}),
        require_qmt_healthy=True,
        account_max_age_seconds=10,
        strategy_max_age_seconds=5,
        market_max_age_seconds=5,
        min_cash_buffer=Decimal("100"),
        fee_buffer_rate=Decimal("0.01"),
        max_account_gross_exposure=Decimal("1000000"),
        max_daily_loss_abs=Decimal("10000"),
        max_daily_turnover=Decimal("1000000"),
        max_daily_orders=100,
        max_daily_cancels=100,
        max_order_notional=Decimal("100000"),
        max_security_gross_exposure=Decimal("500000"),
        max_price_deviation_rate=Decimal("0.10"),
        strategy=StrategyPolicy(
            strategy_id="s1",
            allowed_versions=frozenset({"v1"}),
            allowed_symbols=frozenset({"510300.SH", "01810.SGT"}),
            max_gross_exposure=Decimal("500000"),
            max_daily_turnover=Decimal("500000"),
            max_position_count=10,
        ),
    )


def expected():
    return ReleaseManifest(
        application_build="host-prod-ready-1",
        git_commit=GIT_SHA,
        schema_version=SUPPORTED_SCHEMA_VERSION,
        terminal_instance_id="guojin_sim",
        qmt_bridge_build="p5-simulation-calibration-8",
        config_digest=canonical_config_digest({"profile": "sim"}),
        created_at=NOW,
    )


def observed(**changes):
    exp = expected()
    values = dict(
        application_build=exp.application_build,
        git_commit=exp.git_commit,
        binary_supported_schema_version=SUPPORTED_SCHEMA_VERSION,
        database_schema_version=SUPPORTED_SCHEMA_VERSION,
        terminal_instance_id=exp.terminal_instance_id,
        qmt_bridge_build=exp.qmt_bridge_build,
        config_digest=exp.config_digest,
    )
    values.update(changes)
    return ObservedDeployment(**values)


def database(tmp_path):
    conn = connect_database(tmp_path / "runtime.sqlite3")
    initialize_database(conn)
    return conn


def bootstrap(conn, **changes):
    values = dict(
        expected_release=expected(),
        observed_deployment=observed(),
        runtime_session_id="host-session-1",
        started_at=NOW,
        account_fingerprint=FP,
        policy=policy(),
        required_symbols=("510300.SH", "01810.SGT"),
        required_strategies=(StrategyHealthRequirement("s1", "v1"),),
        health_max_age_seconds=5,
    )
    values.update(changes)
    return bootstrap_runtime_services(conn, **values)


def test_bootstrap_builds_all_services_but_starts_disabled(tmp_path):
    conn = database(tmp_path)

    bundle = bootstrap(conn)

    assert bundle.modes.mode is RuntimeMode.DISABLED
    status = bundle.operations.status(now=NOW, max_age_seconds=5)
    assert status.mode is RuntimeMode.DISABLED
    assert not status.ready_for_mutation
    telemetry = bundle.telemetry.snapshot()
    assert telemetry.mode is RuntimeMode.DISABLED
    assert not telemetry.ready_for_mutation
    assert telemetry.active_alerts == ()
    cycle = bundle.supervisor.tick(
        now=NOW,
        unknown_order_count=0,
        manual_review_count=0,
        halt_request_id="bootstrap-health-cycle",
    )
    assert not cycle.auto_halted
    assert cycle.telemetry.mode is RuntimeMode.DISABLED
    assert bundle.market_data.symbols() == ()
    assert not hasattr(bundle.operations, "arm_live")
    assert not hasattr(bundle.operations, "arm_live_canary")


def test_deployment_mismatch_fails_before_startup_mode_audit(tmp_path):
    conn = database(tmp_path)

    with pytest.raises(DeploymentMismatch):
        bootstrap(
            conn,
            observed_deployment=observed(qmt_bridge_build="wrong-build"),
        )

    count = conn.execute(
        "SELECT COUNT(*) FROM runtime_mode_transitions"
    ).fetchone()[0]
    assert count == 0


def test_runtime_refuses_observed_schema_that_disagrees_with_actual_database(tmp_path):
    conn = database(tmp_path)

    with pytest.raises(
        DeploymentMismatch,
        match="OBSERVED_DATABASE_SCHEMA_MISMATCH",
    ):
        bootstrap(
            conn,
            observed_deployment=observed(
                database_schema_version=SUPPORTED_SCHEMA_VERSION - 1
            ),
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM runtime_mode_transitions"
    ).fetchone()[0] == 0


def test_bootstrap_does_not_auto_migrate_old_database(tmp_path):
    conn = database(tmp_path)
    conn.execute(
        "DELETE FROM schema_meta WHERE version=?",
        (SUPPORTED_SCHEMA_VERSION,),
    )
    conn.commit()

    with pytest.raises(
        DeploymentMismatch,
        match="DATABASE_SCHEMA_DOES_NOT_MATCH_BINARY_CONSTANT",
    ):
        bootstrap(conn)

    assert conn.execute(
        "SELECT COUNT(*) FROM runtime_mode_transitions"
    ).fetchone()[0] == 0


def test_policy_account_and_required_universe_must_match_runtime(tmp_path):
    conn = database(tmp_path)

    with pytest.raises(ValueError, match="policy account fingerprint"):
        bootstrap(
            conn,
            account_fingerprint="sha256:" + "c" * 64,
        )

    with pytest.raises(ValueError, match="complete strategy symbol"):
        bootstrap(
            conn,
            required_symbols=("510300.SH",),
        )


def test_restart_creates_new_disabled_session_not_restored_authority(tmp_path):
    path = tmp_path / "restart.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    first = bootstrap(conn)
    first.operations.enter_observe(
        request_id="observe-1",
        actor="test",
        reason="preflight",
        now=NOW,
        max_age_seconds=5,
    )
    assert first.modes.mode is RuntimeMode.OBSERVE
    conn.close()

    conn = connect_database(path)
    second = bootstrap(
        conn,
        runtime_session_id="host-session-2",
        started_at=NOW + timedelta(minutes=1),
    )
    assert second.modes.mode is RuntimeMode.DISABLED
