from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.core import ExecutionCore
from bigqmt_autotrader.domain import OrderIntent, OrderStatus, Side
from bigqmt_autotrader.drivers import SimulatedDriver, SubmitFailureMode


FP = "sha256:" + "c" * 64
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _intent(client_order_id: str) -> OrderIntent:
    return OrderIntent(
        client_order_id=client_order_id,
        strategy_id="core-golden",
        strategy_version="1",
        account_fingerprint=FP,
        symbol="510300.SH",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("4.60"),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        signal_id=client_order_id,
        reason_code="CORE_GOLDEN",
    )


def test_core_v1_submit_success_golden(tmp_path):
    driver = SimulatedDriver()
    with ExecutionCore.open(tmp_path / "success.sqlite3", driver, clock=lambda: NOW) as core:
        core.recover()
        result = core.submit(_intent("golden-success"))
        assert result.status is OrderStatus.ACKNOWLEDGED
        assert driver.submit_call_count(FP, "golden-success") == 1


def test_core_v1_unknown_then_restart_reconcile_golden(tmp_path):
    path = tmp_path / "unknown.sqlite3"
    driver = SimulatedDriver()
    driver.fail_next_submit(SubmitFailureMode.TIMEOUT_AFTER_ACCEPT)

    with ExecutionCore.open(path, driver, clock=lambda: NOW) as core:
        core.recover()
        first = core.submit(_intent("golden-unknown"))
        assert first.status is OrderStatus.UNKNOWN
        assert driver.submit_call_count(FP, "golden-unknown") == 1

    with ExecutionCore.open(
        path,
        driver,
        clock=lambda: NOW + timedelta(seconds=1),
    ) as recovered:
        recovered.recover()
        assert recovered.oms.repository.get_status(FP, "golden-unknown") is OrderStatus.ACKNOWLEDGED
        assert driver.submit_call_count(FP, "golden-unknown") == 1
