from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from bigqmt_autotrader.market_data import MarketDataService

from .models import (
    AccountRiskSnapshot,
    RiskPolicy,
    RiskSnapshot,
    RuntimeMode,
    SecurityRiskSnapshot,
    StrategyRiskSnapshot,
)


@dataclass(frozen=True)
class SecurityRiskReference:
    """Normalized non-price security facts used to assemble a RiskSnapshot.

    Quote price and quote freshness deliberately do not live here; those come
    exclusively from MarketDataService so runtime code cannot silently pass a
    position last-price or an arbitrary caller-supplied reference price.
    """

    symbol: str
    tick_size: Decimal
    lower_price_limit: Decimal
    upper_price_limit: Decimal
    buy_lot_size: int
    sell_lot_size: int
    sellable_quantity: int
    gross_exposure: Decimal


class RiskSnapshotBuilder:
    """Assemble the canonical RiskSnapshot from trusted normalized facts."""

    def __init__(self, market_data: MarketDataService) -> None:
        if not isinstance(market_data, MarketDataService):
            raise TypeError("market_data must be MarketDataService")
        self._market_data = market_data

    def build(
        self,
        *,
        policy: RiskPolicy,
        now: datetime,
        mode: RuntimeMode,
        database_healthy: bool,
        oms_healthy: bool,
        leader_held: bool,
        reconciliation_complete: bool,
        qmt_healthy: bool,
        market_open: bool,
        global_ambiguity_block: bool,
        blocked_symbols: frozenset[str],
        account: AccountRiskSnapshot,
        strategy: StrategyRiskSnapshot,
        security: SecurityRiskReference,
    ) -> RiskSnapshot:
        if not isinstance(policy, RiskPolicy):
            raise TypeError("policy must be RiskPolicy")
        if not isinstance(security, SecurityRiskReference):
            raise TypeError("security must be SecurityRiskReference")

        quote = self._market_data.latest(
            security.symbol,
            now=now,
            max_age_seconds=policy.market_max_age_seconds,
        )

        security_snapshot = SecurityRiskSnapshot(
            symbol=security.symbol,
            tick_size=security.tick_size,
            lower_price_limit=security.lower_price_limit,
            upper_price_limit=security.upper_price_limit,
            reference_price=quote.last_price,
            buy_lot_size=security.buy_lot_size,
            sell_lot_size=security.sell_lot_size,
            sellable_quantity=security.sellable_quantity,
            gross_exposure=security.gross_exposure,
            observed_at=quote.broker_time,
        )

        return RiskSnapshot(
            mode=mode,
            database_healthy=database_healthy,
            oms_healthy=oms_healthy,
            leader_held=leader_held,
            reconciliation_complete=reconciliation_complete,
            qmt_healthy=qmt_healthy,
            market_open=market_open,
            global_ambiguity_block=global_ambiguity_block,
            blocked_symbols=blocked_symbols,
            account=account,
            strategy=strategy,
            security=security_snapshot,
        )
