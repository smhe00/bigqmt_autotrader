from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from bigqmt_autotrader.market_data import MarketDataService
from bigqmt_autotrader.operations import RuntimeHealth
from bigqmt_autotrader.risk import (
    AccountRiskSnapshot,
    DailyRiskLedger,
    RiskPolicy,
    RiskSnapshot,
    RiskSnapshotBuilder,
    RuntimeMode,
    SecurityRiskReference,
    StrategyRiskSnapshot,
)
from bigqmt_autotrader.strategy_api import StrategyRuntimeService


class RuntimeRiskUnavailable(RuntimeError):
    pass


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class AccountState:
    account_fingerprint: str
    available_cash: Decimal
    gross_exposure: Decimal
    observed_at: datetime


@dataclass(frozen=True)
class StrategyState:
    strategy_id: str
    strategy_version: str
    gross_exposure: Decimal
    security_gross_exposure: Decimal
    position_count: int


class RuntimeRiskAssembler:
    """Build one canonical RiskSnapshot from normalized runtime services."""

    def __init__(
        self,
        *,
        market_data: MarketDataService,
        daily_risk: DailyRiskLedger,
        strategies: StrategyRuntimeService,
    ) -> None:
        if not isinstance(market_data, MarketDataService):
            raise TypeError("market_data must be MarketDataService")
        if not isinstance(daily_risk, DailyRiskLedger):
            raise TypeError("daily_risk must be DailyRiskLedger")
        if not isinstance(strategies, StrategyRuntimeService):
            raise TypeError("strategies must be StrategyRuntimeService")
        self._market_data = market_data
        self._daily_risk = daily_risk
        self._strategies = strategies
        self._snapshot_builder = RiskSnapshotBuilder(market_data)

    def build(
        self,
        *,
        policy: RiskPolicy,
        trading_date: date,
        now: datetime,
        mode: RuntimeMode,
        health: RuntimeHealth,
        market_open: bool,
        global_ambiguity_block: bool,
        blocked_symbols: frozenset[str],
        account: AccountState,
        strategy: StrategyState,
        security: SecurityRiskReference,
    ) -> RiskSnapshot:
        if not isinstance(policy, RiskPolicy):
            raise TypeError("policy must be RiskPolicy")
        if not isinstance(trading_date, date) or isinstance(trading_date, datetime):
            raise TypeError("trading_date must be datetime.date")
        _require_aware("now", now)
        if not isinstance(mode, RuntimeMode):
            raise TypeError("mode must be RuntimeMode")
        if not isinstance(health, RuntimeHealth):
            raise TypeError("health must be RuntimeHealth")
        if not isinstance(account, AccountState):
            raise TypeError("account must be AccountState")
        if not isinstance(strategy, StrategyState):
            raise TypeError("strategy must be StrategyState")
        if not isinstance(security, SecurityRiskReference):
            raise TypeError("security must be SecurityRiskReference")

        totals = self._daily_risk.totals(
            account_fingerprint=account.account_fingerprint,
            trading_date=trading_date,
        )
        if totals.pnl_observed_at > now:
            raise RuntimeRiskUnavailable("daily PnL snapshot is future-dated")
        if now - totals.pnl_observed_at > timedelta(seconds=policy.account_max_age_seconds):
            raise RuntimeRiskUnavailable("daily PnL snapshot is stale")

        heartbeat = self._strategies.require_fresh(
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.strategy_version,
            now=now,
            max_age_seconds=policy.strategy_max_age_seconds,
        )

        account_snapshot = AccountRiskSnapshot(
            account_fingerprint=account.account_fingerprint,
            available_cash=account.available_cash,
            gross_exposure=account.gross_exposure,
            daily_pnl=totals.daily_pnl,
            daily_turnover=totals.daily_turnover,
            daily_order_count=totals.daily_order_count,
            daily_cancel_count=totals.daily_cancel_count,
            observed_at=account.observed_at,
        )
        strategy_snapshot = StrategyRiskSnapshot(
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.strategy_version,
            gross_exposure=strategy.gross_exposure,
            security_gross_exposure=strategy.security_gross_exposure,
            daily_turnover=self._daily_risk.strategy_turnover(
                account_fingerprint=account.account_fingerprint,
                strategy_id=strategy.strategy_id,
                trading_date=trading_date,
            ),
            position_count=strategy.position_count,
            heartbeat_at=heartbeat.observed_at,
        )

        return self._snapshot_builder.build(
            policy=policy,
            now=now,
            mode=mode,
            database_healthy=health.database_healthy,
            oms_healthy=health.oms_healthy,
            leader_held=health.leader_held,
            reconciliation_complete=health.reconciliation_complete,
            qmt_healthy=health.qmt_healthy,
            market_open=market_open,
            global_ambiguity_block=global_ambiguity_block,
            blocked_symbols=blocked_symbols,
            account=account_snapshot,
            strategy=strategy_snapshot,
            security=security,
        )
