from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from bigqmt_autotrader.domain import OrderIntent, RiskDecision, RiskReasonCode, Side

from .canonical import snapshot_hash
from .models import (
    RiskEvaluation,
    RiskFinding,
    RiskLevel,
    RiskPolicy,
    RiskSnapshot,
)


_SUPPORTED_SUFFIXES = (".SH", ".SZ", ".BJ", ".HGT")


def _require_aware_now(now: datetime) -> None:
    if not isinstance(now, datetime):
        raise TypeError("now must be datetime")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def _is_stale(observed_at: datetime, now: datetime, max_age_seconds: int) -> bool:
    # Future-dated risk facts are not silently trusted either. Clock skew must be
    # resolved upstream instead of becoming execution authority.
    return observed_at > now or observed_at < now - timedelta(seconds=max_age_seconds)


def _projected_long_exposure(
    *,
    side: Side,
    current_total: Decimal,
    current_symbol: Decimal,
    order_notional: Decimal,
) -> Decimal:
    if side is Side.BUY:
        return current_total + order_notional
    reduction = min(current_symbol, order_notional)
    return max(Decimal("0"), current_total - reduction)


def evaluate_risk(
    intent: OrderIntent,
    snapshot: RiskSnapshot,
    policy: RiskPolicy,
    *,
    now: datetime,
) -> RiskEvaluation:
    """Evaluate one immutable risk snapshot in deterministic rule order.

    All findings are returned for audit. The first finding is the stable primary
    rejection reason persisted in RiskDecision. No rule mutates input state.
    """
    if not isinstance(intent, OrderIntent):
        raise TypeError("intent must be OrderIntent")
    if not isinstance(snapshot, RiskSnapshot):
        raise TypeError("snapshot must be RiskSnapshot")
    if not isinstance(policy, RiskPolicy):
        raise TypeError("policy must be RiskPolicy")
    _require_aware_now(now)

    findings: list[RiskFinding] = []

    def reject(level: RiskLevel, rule_id: str, code: RiskReasonCode, message: str) -> None:
        findings.append(
            RiskFinding(
                level=level,
                rule_id=rule_id,
                reason_code=code,
                message=message,
            )
        )

    order_notional = intent.limit_price * Decimal(intent.quantity)

    # ------------------------------------------------------------------
    # GLOBAL — fixed deterministic order
    # ------------------------------------------------------------------
    if not snapshot.database_healthy:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_DATABASE_HEALTH",
            RiskReasonCode.DATABASE_UNHEALTHY,
            "database health is not confirmed",
        )
    if not snapshot.oms_healthy:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_OMS_HEALTH",
            RiskReasonCode.DATA_STALE,
            "OMS health is not confirmed",
        )
    if not snapshot.leader_held:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_LEADER_HELD",
            RiskReasonCode.LEADER_NOT_HELD,
            "active OMS leader ownership is not confirmed",
        )
    if not snapshot.reconciliation_complete:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_RECONCILIATION_COMPLETE",
            RiskReasonCode.DATA_STALE,
            "startup reconciliation is incomplete",
        )
    if snapshot.mode not in policy.permitted_execution_modes:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_RUNTIME_MODE",
            RiskReasonCode.MODE_NOT_ARMED,
            f"runtime mode {snapshot.mode.value} is not permitted by this risk policy",
        )
    if policy.require_qmt_healthy and not snapshot.qmt_healthy:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_QMT_HEALTH",
            RiskReasonCode.DATA_STALE,
            "required QMT health is not confirmed",
        )
    if snapshot.global_ambiguity_block:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_BLOCKING_AMBIGUITY",
            RiskReasonCode.UNKNOWN_ORDER,
            "account-wide unresolved execution ambiguity blocks new exposure",
        )
    if not snapshot.market_open:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_MARKET_OPEN",
            RiskReasonCode.MARKET_CLOSED,
            "market session is not open for new orders",
        )
    if snapshot.account.daily_pnl < -policy.max_daily_loss_abs:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_DAILY_LOSS_LIMIT",
            RiskReasonCode.LIMIT_EXCEEDED,
            "daily loss limit has been exceeded",
        )
    if snapshot.account.daily_turnover + order_notional > policy.max_daily_turnover:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_DAILY_TURNOVER_LIMIT",
            RiskReasonCode.LIMIT_EXCEEDED,
            "projected daily turnover exceeds the account policy limit",
        )
    if snapshot.account.daily_order_count + 1 > policy.max_daily_orders:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_DAILY_ORDER_LIMIT",
            RiskReasonCode.LIMIT_EXCEEDED,
            "projected daily order count exceeds the policy limit",
        )
    if snapshot.account.daily_cancel_count > policy.max_daily_cancels:
        reject(
            RiskLevel.GLOBAL,
            "GLOBAL_DAILY_CANCEL_LIMIT",
            RiskReasonCode.LIMIT_EXCEEDED,
            "daily cancel count already exceeds the policy limit",
        )

    # ------------------------------------------------------------------
    # ACCOUNT
    # ------------------------------------------------------------------
    if (
        intent.account_fingerprint != policy.expected_account_fingerprint
        or snapshot.account.account_fingerprint != policy.expected_account_fingerprint
        or snapshot.account.account_fingerprint != intent.account_fingerprint
    ):
        reject(
            RiskLevel.ACCOUNT,
            "ACCOUNT_FINGERPRINT_MATCH",
            RiskReasonCode.ACCOUNT_MISMATCH,
            "intent, snapshot and deployed account fingerprints must match",
        )
    if _is_stale(snapshot.account.observed_at, now, policy.account_max_age_seconds):
        reject(
            RiskLevel.ACCOUNT,
            "ACCOUNT_SNAPSHOT_FRESHNESS",
            RiskReasonCode.DATA_STALE,
            "account cash/position snapshot is stale or future-dated",
        )
    if snapshot.security.gross_exposure > snapshot.account.gross_exposure:
        reject(
            RiskLevel.ACCOUNT,
            "ACCOUNT_SNAPSHOT_CONSISTENCY",
            RiskReasonCode.DATA_STALE,
            "security exposure exceeds account gross exposure",
        )
    if snapshot.strategy.gross_exposure > snapshot.account.gross_exposure:
        reject(
            RiskLevel.ACCOUNT,
            "ACCOUNT_STRATEGY_EXPOSURE_CONSISTENCY",
            RiskReasonCode.DATA_STALE,
            "strategy exposure exceeds account gross exposure",
        )
    if snapshot.account.available_cash < policy.min_cash_buffer:
        reject(
            RiskLevel.ACCOUNT,
            "ACCOUNT_MIN_CASH_BUFFER",
            RiskReasonCode.LIMIT_EXCEEDED,
            "available cash is already below the minimum cash buffer",
        )

    projected_account_exposure = _projected_long_exposure(
        side=intent.side,
        current_total=snapshot.account.gross_exposure,
        current_symbol=snapshot.security.gross_exposure,
        order_notional=order_notional,
    )
    if projected_account_exposure > policy.max_account_gross_exposure:
        reject(
            RiskLevel.ACCOUNT,
            "ACCOUNT_PROJECTED_EXPOSURE",
            RiskReasonCode.LIMIT_EXCEEDED,
            "projected account gross exposure exceeds the policy limit",
        )

    # ------------------------------------------------------------------
    # STRATEGY
    # ------------------------------------------------------------------
    if (
        intent.strategy_id != policy.strategy.strategy_id
        or snapshot.strategy.strategy_id != policy.strategy.strategy_id
        or snapshot.strategy.strategy_id != intent.strategy_id
        or intent.strategy_version not in policy.strategy.allowed_versions
        or snapshot.strategy.strategy_version != intent.strategy_version
    ):
        reject(
            RiskLevel.STRATEGY,
            "STRATEGY_ID_VERSION_ALLOWLIST",
            RiskReasonCode.STRATEGY_NOT_ALLOWED,
            "strategy identity/version is not allow-listed or snapshot identity differs",
        )
    if _is_stale(snapshot.strategy.heartbeat_at, now, policy.strategy_max_age_seconds):
        reject(
            RiskLevel.STRATEGY,
            "STRATEGY_HEARTBEAT_FRESHNESS",
            RiskReasonCode.DATA_STALE,
            "strategy heartbeat is stale or future-dated",
        )
    if intent.symbol not in policy.strategy.allowed_symbols:
        reject(
            RiskLevel.STRATEGY,
            "STRATEGY_SYMBOL_UNIVERSE",
            RiskReasonCode.STRATEGY_NOT_ALLOWED,
            "symbol is outside the strategy allow-list",
        )

    projected_strategy_exposure = _projected_long_exposure(
        side=intent.side,
        current_total=snapshot.strategy.gross_exposure,
        current_symbol=snapshot.strategy.security_gross_exposure,
        order_notional=order_notional,
    )
    if projected_strategy_exposure > policy.strategy.max_gross_exposure:
        reject(
            RiskLevel.STRATEGY,
            "STRATEGY_PROJECTED_EXPOSURE",
            RiskReasonCode.LIMIT_EXCEEDED,
            "projected strategy gross exposure exceeds its capital budget",
        )
    if snapshot.strategy.daily_turnover + order_notional > policy.strategy.max_daily_turnover:
        reject(
            RiskLevel.STRATEGY,
            "STRATEGY_DAILY_TURNOVER_LIMIT",
            RiskReasonCode.LIMIT_EXCEEDED,
            "projected strategy daily turnover exceeds its limit",
        )

    projected_position_count = snapshot.strategy.position_count
    if intent.side is Side.BUY and snapshot.strategy.security_gross_exposure == 0:
        projected_position_count += 1
    elif (
        intent.side is Side.SELL
        and snapshot.strategy.security_gross_exposure > 0
        and order_notional >= snapshot.strategy.security_gross_exposure
    ):
        projected_position_count = max(0, projected_position_count - 1)
    if projected_position_count > policy.strategy.max_position_count:
        reject(
            RiskLevel.STRATEGY,
            "STRATEGY_POSITION_COUNT_LIMIT",
            RiskReasonCode.LIMIT_EXCEEDED,
            "projected strategy position count exceeds its limit",
        )

    # ------------------------------------------------------------------
    # SECURITY / ORDER
    # ------------------------------------------------------------------
    if intent.is_expired(now):
        reject(
            RiskLevel.ORDER,
            "ORDER_INTENT_EXPIRY",
            RiskReasonCode.INTENT_EXPIRED,
            "order intent has expired",
        )
    if snapshot.security.symbol != intent.symbol or not intent.symbol.endswith(_SUPPORTED_SUFFIXES):
        reject(
            RiskLevel.ORDER,
            "ORDER_SECURITY_SUPPORTED",
            RiskReasonCode.INVALID_ORDER,
            "security snapshot must match intent and use a supported A-share market suffix",
        )
    if _is_stale(snapshot.security.observed_at, now, policy.market_max_age_seconds):
        reject(
            RiskLevel.ORDER,
            "ORDER_MARKET_DATA_FRESHNESS",
            RiskReasonCode.DATA_STALE,
            "market/security snapshot is stale or future-dated",
        )
    if intent.symbol in snapshot.blocked_symbols:
        reject(
            RiskLevel.ORDER,
            "ORDER_SYMBOL_AMBIGUITY",
            RiskReasonCode.UNKNOWN_ORDER,
            "unresolved order ambiguity blocks new exposure for this symbol",
        )
    if intent.limit_price % snapshot.security.tick_size != 0:
        reject(
            RiskLevel.ORDER,
            "ORDER_TICK_SIZE",
            RiskReasonCode.INVALID_ORDER,
            "limit price is not aligned to the supplied tick size",
        )
    if not (
        snapshot.security.lower_price_limit
        <= intent.limit_price
        <= snapshot.security.upper_price_limit
    ):
        reject(
            RiskLevel.ORDER,
            "ORDER_PRICE_BAND",
            RiskReasonCode.INVALID_ORDER,
            "limit price is outside the supplied daily price band",
        )

    deviation = abs(intent.limit_price - snapshot.security.reference_price) / snapshot.security.reference_price
    if deviation > policy.max_price_deviation_rate:
        reject(
            RiskLevel.ORDER,
            "ORDER_REFERENCE_PRICE_DEVIATION",
            RiskReasonCode.INVALID_ORDER,
            "limit price deviation from reference price exceeds the policy limit",
        )

    lot_size = (
        snapshot.security.buy_lot_size
        if intent.side is Side.BUY
        else snapshot.security.sell_lot_size
    )
    if intent.quantity % lot_size != 0:
        reject(
            RiskLevel.ORDER,
            "ORDER_LOT_SIZE",
            RiskReasonCode.INVALID_ORDER,
            "order quantity is not aligned to the supplied lot rule",
        )
    if order_notional > policy.max_order_notional:
        reject(
            RiskLevel.ORDER,
            "ORDER_NOTIONAL_LIMIT",
            RiskReasonCode.LIMIT_EXCEEDED,
            "single-order notional exceeds the policy limit",
        )

    projected_security_exposure = _projected_long_exposure(
        side=intent.side,
        current_total=snapshot.security.gross_exposure,
        current_symbol=snapshot.security.gross_exposure,
        order_notional=order_notional,
    )
    if projected_security_exposure > policy.max_security_gross_exposure:
        reject(
            RiskLevel.ORDER,
            "ORDER_SECURITY_EXPOSURE_LIMIT",
            RiskReasonCode.LIMIT_EXCEEDED,
            "projected security exposure exceeds the policy limit",
        )

    if intent.side is Side.BUY:
        required_cash = order_notional * (Decimal("1") + policy.fee_buffer_rate)
        if snapshot.account.available_cash - required_cash < policy.min_cash_buffer:
            reject(
                RiskLevel.ORDER,
                "ORDER_BUY_CASH_WITH_FEE_BUFFER",
                RiskReasonCode.LIMIT_EXCEEDED,
                "buy cost plus fee buffer would violate available-cash reserve",
            )
    elif intent.quantity > snapshot.security.sellable_quantity:
        reject(
            RiskLevel.ORDER,
            "ORDER_SELLABLE_QUANTITY",
            RiskReasonCode.LIMIT_EXCEEDED,
            "sell quantity exceeds explicit sellable quantity",
        )

    findings_tuple = tuple(findings)
    primary_code = findings_tuple[0].reason_code if findings_tuple else RiskReasonCode.OK
    decision = RiskDecision(
        accepted=not findings_tuple,
        reason_code=primary_code,
        rule_version=policy.rule_version,
        snapshot_hash=snapshot_hash(snapshot),
        decided_at=now,
    )
    return RiskEvaluation(decision=decision, findings=findings_tuple)
