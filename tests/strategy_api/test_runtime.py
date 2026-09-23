from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.domain import OrderIntent, Side
from bigqmt_autotrader.strategy_api import (
    HeartbeatUpdateResult,
    StrategyHeartbeat,
    StrategyIdentityMismatch,
    StrategyRuntimeService,
    StrategyStale,
    StrategyUnavailable,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 10, 30, tzinfo=TZ)


def heartbeat(*, session: str = "session-1", sequence: int = 1, age: int = 0, version: str = "v1"):
    return StrategyHeartbeat(
        strategy_id="strategy-a",
        strategy_version=version,
        session_id=session,
        sequence=sequence,
        observed_at=NOW - timedelta(seconds=age),
    )


def intent(*, version: str = "v1") -> OrderIntent:
    return OrderIntent(
        client_order_id="coid-1",
        strategy_id="strategy-a",
        strategy_version=version,
        account_fingerprint="acct",
        symbol="510300.SH",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("4.64"),
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        signal_id="signal-1",
        reason_code="test",
    )


def test_intent_requires_a_live_strategy_heartbeat():
    service = StrategyRuntimeService()
    with pytest.raises(StrategyUnavailable):
        service.authorize_intent(intent(), now=NOW, max_age_seconds=5)


def test_fresh_matching_heartbeat_authorizes_intent():
    service = StrategyRuntimeService()
    hb = heartbeat()
    assert service.ingest_heartbeat(hb) is HeartbeatUpdateResult.APPLIED
    assert service.authorize_intent(intent(), now=NOW, max_age_seconds=5) == hb


def test_stale_and_future_heartbeats_fail_closed():
    stale = StrategyRuntimeService()
    stale.ingest_heartbeat(heartbeat(age=10))
    with pytest.raises(StrategyStale, match="stale"):
        stale.require_fresh(
            strategy_id="strategy-a", strategy_version="v1", now=NOW, max_age_seconds=5
        )

    future = StrategyRuntimeService()
    future.ingest_heartbeat(
        StrategyHeartbeat(
            strategy_id="strategy-a", strategy_version="v1", session_id="s",
            sequence=1, observed_at=NOW + timedelta(seconds=1)
        )
    )
    with pytest.raises(StrategyStale, match="future-dated"):
        future.require_fresh(
            strategy_id="strategy-a", strategy_version="v1", now=NOW, max_age_seconds=5
        )


def test_version_mismatch_fails_closed():
    service = StrategyRuntimeService()
    service.ingest_heartbeat(heartbeat(version="v2"))
    with pytest.raises(StrategyIdentityMismatch):
        service.authorize_intent(intent(version="v1"), now=NOW, max_age_seconds=5)


def test_same_session_sequence_is_monotonic_and_idempotent():
    service = StrategyRuntimeService()
    first = heartbeat(sequence=2, age=2)
    older_sequence = heartbeat(sequence=1, age=1)
    assert service.ingest_heartbeat(first) is HeartbeatUpdateResult.APPLIED
    assert service.ingest_heartbeat(first) is HeartbeatUpdateResult.DUPLICATE
    assert service.ingest_heartbeat(older_sequence) is HeartbeatUpdateResult.STALE_IGNORED
    assert service.require_fresh(
        strategy_id="strategy-a", strategy_version="v1", now=NOW, max_age_seconds=5
    ) == first


def test_new_strategy_session_must_be_strictly_newer():
    service = StrategyRuntimeService()
    old = heartbeat(session="old", sequence=5, age=2)
    rejected = heartbeat(session="new", sequence=1, age=3)
    accepted = heartbeat(session="new", sequence=1, age=1)
    assert service.ingest_heartbeat(old) is HeartbeatUpdateResult.APPLIED
    assert service.ingest_heartbeat(rejected) is HeartbeatUpdateResult.STALE_IGNORED
    assert service.ingest_heartbeat(accepted) is HeartbeatUpdateResult.APPLIED


def test_runtime_restart_does_not_reuse_persisted_liveness():
    first = StrategyRuntimeService()
    first.ingest_heartbeat(heartbeat())
    second = StrategyRuntimeService()
    with pytest.raises(StrategyUnavailable):
        second.require_fresh(
            strategy_id="strategy-a", strategy_version="v1", now=NOW, max_age_seconds=5
        )
