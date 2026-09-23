from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from bigqmt_autotrader.domain import OrderIntent, RiskDecision, RiskReasonCode


def execution_intent_digest(intent: OrderIntent) -> str:
    """Stable Core-plane digest for durable execution authorization."""
    if not isinstance(intent, OrderIntent):
        raise TypeError("intent must be OrderIntent")
    payload = {
        "account_fingerprint": intent.account_fingerprint,
        "client_order_id": intent.client_order_id,
        "strategy_id": intent.strategy_id,
        "strategy_version": intent.strategy_version,
        "symbol": intent.symbol,
        "side": intent.side.value,
        "quantity": intent.quantity,
        "limit_price": str(intent.limit_price),
        "created_at": intent.created_at.isoformat(),
        "expires_at": intent.expires_at.isoformat(),
        "signal_id": intent.signal_id,
        "reason_code": intent.reason_code,
        "order_type": intent.order_type.value,
    }
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def core_execution_decision(
    intent: OrderIntent,
    *,
    now: datetime | None = None,
    rule_version: str = "execution-core-v1",
) -> RiskDecision:
    """Create execution authority without importing Production Risk runtime.

    RiskDecision is retained as the durable P1 schema record for backward
    compatibility. In Core mode it represents execution authorization, not
    a policy/risk evaluation.
    """
    if not isinstance(rule_version, str) or not rule_version.strip():
        raise ValueError("rule_version must be non-empty")
    decided_at = now or datetime.now(timezone.utc)
    if decided_at.tzinfo is None or decided_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return RiskDecision(
        accepted=True,
        reason_code=RiskReasonCode.OK,
        rule_version=rule_version,
        snapshot_hash=execution_intent_digest(intent),
        decided_at=decided_at,
    )
