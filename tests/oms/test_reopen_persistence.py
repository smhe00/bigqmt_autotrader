from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskDecision, RiskReasonCode, Side
from bigqmt_autotrader.drivers import SimulatedDriver
from bigqmt_autotrader.oms import OfflineOms, OmsRepository, connect_database, initialize_database


def test_order_state_survives_database_reopen(tmp_path):
    path = tmp_path / "oms.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    repo = OmsRepository(conn)
    driver = SimulatedDriver()
    oms = OfflineOms(repo, driver)
    oms.recover()

    created = datetime(2026, 9, 12, 9, 40, tzinfo=timezone(timedelta(hours=8)))
    order_intent = OrderIntent(
        client_order_id="cid-reopen",
        strategy_id="strategyA",
        strategy_version="git:test",
        account_fingerprint="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        symbol="000333.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("75.00"),
        created_at=created,
        expires_at=created + timedelta(minutes=1),
        signal_id="signal-reopen",
        reason_code="TARGET_POSITION_REBALANCE",
    )
    decision = RiskDecision(
        accepted=True,
        reason_code=RiskReasonCode.OK,
        rule_version="p1-test",
        snapshot_hash="sha256:test",
        decided_at=datetime.now(timezone.utc),
    )
    oms.submit_intent(order_intent, decision)
    conn.close()

    reopened = connect_database(path)
    initialize_database(reopened)
    reopened_repo = OmsRepository(reopened)
    assert reopened_repo.get_status("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-reopen") is OrderStatus.ACKNOWLEDGED
