from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from bigqmt_autotrader.domain import OrderIntent, Side
from bigqmt_autotrader.drivers import QmtShadowDriver, SubmitOutcomeUnknown
from bigqmt_autotrader.qmt import QmtCommandSpool


FP = "sha256:" + "c" * 64


def intent(now: datetime) -> OrderIntent:
    return OrderIntent(
        client_order_id="cid-shadow-001",
        strategy_id="strategy",
        strategy_version="1",
        account_fingerprint=FP,
        symbol="000001.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("10.50"),
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        signal_id="signal-1",
        reason_code="shadow-test",
    )


def test_shadow_driver_publishes_durable_command_but_never_fakes_broker_ack(tmp_path):
    now = datetime.now(timezone.utc)
    spool = QmtCommandSpool(tmp_path)
    driver = QmtShadowDriver(spool)

    with pytest.raises(SubmitOutcomeUnknown):
        driver.submit_limit_order(intent(now))

    files = list(spool.inbox.glob("*.json"))
    assert len(files) == 1
    frame = json.loads(files[0].read_text(encoding="utf-8"))
    command = frame["command"]
    assert command["command_type"] == "SUBMIT_LIMIT"
    assert command["client_order_id"] == "cid-shadow-001"
    assert command["payload"]["side"] == "BUY"
    assert command["payload"]["limit_price"] == "10.50"
    assert len(command["broker_token"]) < 24
    assert driver.query_by_client_order_id(FP, "cid-shadow-001") is None


def test_shadow_submit_retry_is_same_durable_command_not_second_command(tmp_path):
    now = datetime.now(timezone.utc)
    spool = QmtCommandSpool(tmp_path)
    driver = QmtShadowDriver(spool)
    order_intent = intent(now)

    for _ in range(2):
        with pytest.raises(SubmitOutcomeUnknown):
            driver.submit_limit_order(order_intent)

    assert len(list(spool.inbox.glob("*.json"))) == 1
