from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from bigqmt_autotrader.domain import RiskDecision, RiskReasonCode


class RuntimeMode(str, Enum):
    DISABLED = "DISABLED"
    OBSERVE = "OBSERVE"
    SHADOW = "SHADOW"
    SIMULATION = "SIMULATION"
    LIVE_CANARY = "LIVE_CANARY"
    LIVE_ARMED = "LIVE_ARMED"


class RiskLevel(str, Enum):
    GLOBAL = "GLOBAL"
    ACCOUNT = "ACCOUNT"
    STRATEGY = "STRATEGY"
    ORDER = "SECURITY_ORDER"


def _require_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_bool(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be bool")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_decimal(name: str, value: Decimal, *, minimum: Decimal = Decimal("0")) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be decimal.Decimal; binary float is forbidden")
    if not value.is_finite() or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")


def _require_positive_decimal(name: str, value: Decimal) -> None:
    _require_decimal(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be > 0")


def _require_nonnegative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class StrategyPolicy:
    strategy_id: str
    allowed_versions: frozenset[str]
    allowed_symbols: frozenset[str]
    max_gross_exposure: Decimal
    max_daily_turnover: Decimal
    max_position_count: int

    def __post_init__(self) -> None:
        _require_nonempty("strategy_id", self.strategy_id)
        if not isinstance(self.allowed_versions, frozenset) or not self.allowed_versions:
            raise ValueError("allowed_versions must be a non-empty frozenset")
        if not isinstance(self.allowed_symbols, frozenset) or not self.allowed_symbols:
            raise ValueError("allowed_symbols must be a non-empty frozenset")
        for value in self.allowed_versions:
            _require_nonempty("allowed_versions item", value)
        for value in self.allowed_symbols:
            _require_nonempty("allowed_symbols item", value)
        _require_decimal("max_gross_exposure", self.max_gross_exposure)
        _require_decimal("max_daily_turnover", self.max_daily_turnover)
        _require_nonnegative_int("max_position_count", self.max_position_count)


@dataclass(frozen=True)
class RiskPolicy:
    rule_version: str
    expected_account_fingerprint: str
    permitted_execution_modes: frozenset[RuntimeMode]
    require_qmt_healthy: bool
    account_max_age_seconds: int
    strategy_max_age_seconds: int
    market_max_age_seconds: int
    min_cash_buffer: Decimal
    fee_buffer_rate: Decimal
    max_account_gross_exposure: Decimal
    max_daily_loss_abs: Decimal
    max_daily_turnover: Decimal
    max_daily_orders: int
    max_daily_cancels: int
    max_order_notional: Decimal
    max_security_gross_exposure: Decimal
    max_price_deviation_rate: Decimal
    strategy: StrategyPolicy

    def __post_init__(self) -> None:
        _require_nonempty("rule_version", self.rule_version)
        _require_nonempty("expected_account_fingerprint", self.expected_account_fingerprint)
        if not isinstance(self.permitted_execution_modes, frozenset) or not self.permitted_execution_modes:
            raise ValueError("permitted_execution_modes must be a non-empty frozenset")
        if not all(isinstance(mode, RuntimeMode) for mode in self.permitted_execution_modes):
            raise TypeError("permitted_execution_modes must contain RuntimeMode values")
        if self.permitted_execution_modes != frozenset({RuntimeMode.SIMULATION}):
            raise ValueError(
                "P2 policy may permit SIMULATION only; live modes require a later phase gate"
            )
        _require_bool("require_qmt_healthy", self.require_qmt_healthy)
        _require_positive_int("account_max_age_seconds", self.account_max_age_seconds)
        _require_positive_int("strategy_max_age_seconds", self.strategy_max_age_seconds)
        _require_positive_int("market_max_age_seconds", self.market_max_age_seconds)
        for name in (
            "min_cash_buffer",
            "fee_buffer_rate",
            "max_account_gross_exposure",
            "max_daily_loss_abs",
            "max_daily_turnover",
            "max_order_notional",
            "max_security_gross_exposure",
            "max_price_deviation_rate",
        ):
            _require_decimal(name, getattr(self, name))
        if self.fee_buffer_rate >= Decimal("1"):
            raise ValueError("fee_buffer_rate must be < 1")
        if self.max_price_deviation_rate >= Decimal("1"):
            raise ValueError("max_price_deviation_rate must be < 1")
        _require_nonnegative_int("max_daily_orders", self.max_daily_orders)
        _require_nonnegative_int("max_daily_cancels", self.max_daily_cancels)
        if not isinstance(self.strategy, StrategyPolicy):
            raise TypeError("strategy must be StrategyPolicy")


@dataclass(frozen=True)
class AccountRiskSnapshot:
    account_fingerprint: str
    available_cash: Decimal
    gross_exposure: Decimal
    daily_pnl: Decimal
    daily_turnover: Decimal
    daily_order_count: int
    daily_cancel_count: int
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty("account_fingerprint", self.account_fingerprint)
        _require_decimal("available_cash", self.available_cash)
        _require_decimal("gross_exposure", self.gross_exposure)
        if not isinstance(self.daily_pnl, Decimal):
            raise TypeError("daily_pnl must be decimal.Decimal; binary float is forbidden")
        if not self.daily_pnl.is_finite():
            raise ValueError("daily_pnl must be finite")
        _require_decimal("daily_turnover", self.daily_turnover)
        _require_nonnegative_int("daily_order_count", self.daily_order_count)
        _require_nonnegative_int("daily_cancel_count", self.daily_cancel_count)
        _require_aware("observed_at", self.observed_at)


@dataclass(frozen=True)
class StrategyRiskSnapshot:
    strategy_id: str
    strategy_version: str
    gross_exposure: Decimal
    security_gross_exposure: Decimal
    daily_turnover: Decimal
    position_count: int
    heartbeat_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty("strategy_id", self.strategy_id)
        _require_nonempty("strategy_version", self.strategy_version)
        _require_decimal("gross_exposure", self.gross_exposure)
        _require_decimal("security_gross_exposure", self.security_gross_exposure)
        if self.security_gross_exposure > self.gross_exposure:
            raise ValueError("security_gross_exposure cannot exceed strategy gross_exposure")
        _require_decimal("daily_turnover", self.daily_turnover)
        _require_nonnegative_int("position_count", self.position_count)
        _require_aware("heartbeat_at", self.heartbeat_at)


@dataclass(frozen=True)
class SecurityRiskSnapshot:
    symbol: str
    tick_size: Decimal
    lower_price_limit: Decimal
    upper_price_limit: Decimal
    reference_price: Decimal
    buy_lot_size: int
    sell_lot_size: int
    sellable_quantity: int
    gross_exposure: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty("symbol", self.symbol)
        _require_positive_decimal("tick_size", self.tick_size)
        _require_positive_decimal("lower_price_limit", self.lower_price_limit)
        _require_positive_decimal("upper_price_limit", self.upper_price_limit)
        _require_positive_decimal("reference_price", self.reference_price)
        if self.upper_price_limit < self.lower_price_limit:
            raise ValueError("upper_price_limit must be >= lower_price_limit")
        _require_positive_int("buy_lot_size", self.buy_lot_size)
        _require_positive_int("sell_lot_size", self.sell_lot_size)
        _require_nonnegative_int("sellable_quantity", self.sellable_quantity)
        _require_decimal("gross_exposure", self.gross_exposure)
        _require_aware("observed_at", self.observed_at)


@dataclass(frozen=True)
class RiskSnapshot:
    mode: RuntimeMode
    database_healthy: bool
    oms_healthy: bool
    leader_held: bool
    reconciliation_complete: bool
    qmt_healthy: bool
    market_open: bool
    global_ambiguity_block: bool
    blocked_symbols: frozenset[str]
    account: AccountRiskSnapshot
    strategy: StrategyRiskSnapshot
    security: SecurityRiskSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RuntimeMode):
            raise TypeError("mode must be RuntimeMode")
        for name in (
            "database_healthy",
            "oms_healthy",
            "leader_held",
            "reconciliation_complete",
            "qmt_healthy",
            "market_open",
            "global_ambiguity_block",
        ):
            _require_bool(name, getattr(self, name))
        if not isinstance(self.blocked_symbols, frozenset):
            raise TypeError("blocked_symbols must be frozenset")
        for symbol in self.blocked_symbols:
            _require_nonempty("blocked_symbols item", symbol)
        if not isinstance(self.account, AccountRiskSnapshot):
            raise TypeError("account must be AccountRiskSnapshot")
        if not isinstance(self.strategy, StrategyRiskSnapshot):
            raise TypeError("strategy must be StrategyRiskSnapshot")
        if not isinstance(self.security, SecurityRiskSnapshot):
            raise TypeError("security must be SecurityRiskSnapshot")


@dataclass(frozen=True)
class RiskFinding:
    level: RiskLevel
    rule_id: str
    reason_code: RiskReasonCode
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.level, RiskLevel):
            raise TypeError("level must be RiskLevel")
        _require_nonempty("rule_id", self.rule_id)
        if not isinstance(self.reason_code, RiskReasonCode):
            raise TypeError("reason_code must be RiskReasonCode")
        _require_nonempty("message", self.message)


@dataclass(frozen=True)
class RiskEvaluation:
    decision: RiskDecision
    findings: tuple[RiskFinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.decision, RiskDecision):
            raise TypeError("decision must be RiskDecision")
        if not isinstance(self.findings, tuple) or not all(
            isinstance(item, RiskFinding) for item in self.findings
        ):
            raise TypeError("findings must be tuple[RiskFinding, ...]")
        if self.decision.accepted != (len(self.findings) == 0):
            raise ValueError("decision.accepted must match absence of findings")
        if self.decision.accepted and self.decision.reason_code is not RiskReasonCode.OK:
            raise ValueError("accepted decision must use RISK_OK")
        if self.findings and self.decision.reason_code is not self.findings[0].reason_code:
            raise ValueError("decision reason_code must match first finding")
