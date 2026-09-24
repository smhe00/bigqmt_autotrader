from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.core import CORE_SCHEMA_VERSION, ExecutionCore
from bigqmt_autotrader.domain import OrderIntent, OrderStatus, Side
from bigqmt_autotrader.drivers import SimulatedDriver
from bigqmt_autotrader.oms import current_core_schema_version, current_schema_version


FP = "sha256:" + "a" * 64
NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone(timedelta(hours=8)))


def intent(client_order_id="core-1"):
    return OrderIntent(
        client_order_id=client_order_id,
        strategy_id="manual",
        strategy_version="none",
        account_fingerprint=FP,
        symbol="510300.SH",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("4.60"),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        signal_id="manual",
        reason_code="CORE_DIRECT",
    )


def test_execution_core_uses_only_core_schema_and_submits_without_runtime(tmp_path):
    driver = SimulatedDriver()
    core = ExecutionCore.open(
        tmp_path / "core.sqlite3",
        driver,
        clock=lambda: NOW,
    )
    try:
        assert current_core_schema_version(core.conn) == CORE_SCHEMA_VERSION == 1
        core.recover()
        result = core.submit(intent())
        assert result.status is OrderStatus.ACKNOWLEDGED
        assert result.risk_evaluation is None
        assert driver.submit_call_count(FP, "core-1") == 1

        tables = {
            row["name"]
            for row in core.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert not any(name.startswith("qmt_") for name in tables)
        assert "daily_risk_events" not in tables
        assert "runtime_mode_transitions" not in tables
        assert "operations_alert_events" not in tables
    finally:
        core.close()


def test_execution_core_restart_recovery_remains_available_without_runtime(tmp_path):
    path = tmp_path / "core.sqlite3"
    driver = SimulatedDriver()
    first = ExecutionCore.open(path, driver, clock=lambda: NOW)
    first.recover()
    first.submit(intent())
    first.close()

    second = ExecutionCore.open(
        path,
        driver,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    try:
        second.recover()
        assert current_core_schema_version(second.conn) == 1
    finally:
        second.close()


def test_core_can_open_existing_full_runtime_database_without_downgrade(tmp_path):
    from bigqmt_autotrader.oms import connect_database, initialize_database

    path = tmp_path / "combined.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    assert current_schema_version(conn) == 11
    conn.close()

    core = ExecutionCore.open(path, SimulatedDriver(), clock=lambda: NOW)
    try:
        assert current_schema_version(core.conn) == 11
        assert current_core_schema_version(core.conn) == 1
    finally:
        core.close()
