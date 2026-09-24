from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bigqmt_autotrader.market_data import MarketDataError, MarketDataService
from bigqmt_autotrader.operations import (
    HealthComponent,
    HealthObservation,
    HealthRegistry,
)
from bigqmt_autotrader.core import IngressDisposition, IngressResult
from bigqmt_autotrader.strategy_api import (
    StrategyRuntimeError,
    StrategyRuntimeService,
)


def _event_time(result: IngressResult) -> datetime:
    return datetime.fromtimestamp(
        result.event.timestamp_ms / 1000.0,
        tz=timezone.utc,
    )


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class StrategyHealthRequirement:
    strategy_id: str
    strategy_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_id, str) or not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not isinstance(self.strategy_version, str) or not self.strategy_version:
            raise ValueError("strategy_version must be non-empty")


class RuntimeHealthSynchronizer:
    """Translate normalized runtime facts into fail-closed HealthRegistry facts.

    This class never creates trading authority. It only publishes ephemeral
    health observations. Host restart still starts with no trusted health facts.
    """

    def __init__(
        self,
        *,
        health: HealthRegistry,
        market_data: MarketDataService,
        strategies: StrategyRuntimeService,
        required_symbols: tuple[str, ...],
        required_strategies: tuple[StrategyHealthRequirement, ...],
        market_max_age_seconds: int,
        strategy_max_age_seconds: int,
    ) -> None:
        if not isinstance(health, HealthRegistry):
            raise TypeError("health must be HealthRegistry")
        if not isinstance(market_data, MarketDataService):
            raise TypeError("market_data must be MarketDataService")
        if not isinstance(strategies, StrategyRuntimeService):
            raise TypeError("strategies must be StrategyRuntimeService")
        if not isinstance(required_symbols, tuple) or not required_symbols:
            raise ValueError("required_symbols must be a non-empty tuple")
        if any(not isinstance(symbol, str) or not symbol for symbol in required_symbols):
            raise ValueError("required_symbols must contain non-empty strings")
        if len(set(required_symbols)) != len(required_symbols):
            raise ValueError("required_symbols must be unique")
        if (
            not isinstance(required_strategies, tuple)
            or not required_strategies
            or not all(
                isinstance(item, StrategyHealthRequirement)
                for item in required_strategies
            )
        ):
            raise ValueError(
                "required_strategies must be a non-empty tuple of StrategyHealthRequirement"
            )
        _require_positive_int("market_max_age_seconds", market_max_age_seconds)
        _require_positive_int("strategy_max_age_seconds", strategy_max_age_seconds)
        self._health = health
        self._market_data = market_data
        self._strategies = strategies
        self._required_symbols = required_symbols
        self._required_strategies = required_strategies
        self._market_max_age_seconds = market_max_age_seconds
        self._strategy_max_age_seconds = strategy_max_age_seconds

    def observe_qmt_ingress(self, result: IngressResult) -> bool:
        if not isinstance(result, IngressResult):
            raise TypeError("result must be IngressResult")
        if result.disposition is IngressDisposition.DUPLICATE:
            return False
        healthy = (
            result.disposition is IngressDisposition.ACCEPTED
            and not result.needs_resync
        )
        detail = "" if healthy else (
            "INGRESS_GAP"
            if result.disposition is IngressDisposition.GAP
            else "NEEDS_RESYNC"
        )
        return self._health.observe(
            HealthObservation(
                component=HealthComponent.QMT,
                healthy=healthy,
                observed_at=_event_time(result),
                detail=detail,
            )
        )

    def refresh_market_data(self, *, now: datetime) -> bool:
        failures: list[str] = []
        for symbol in self._required_symbols:
            try:
                self._market_data.latest(
                    symbol,
                    now=now,
                    max_age_seconds=self._market_max_age_seconds,
                )
            except MarketDataError as exc:
                failures.append(f"{symbol}:{type(exc).__name__}")
        return self._health.observe(
            HealthObservation(
                component=HealthComponent.MARKET_DATA,
                healthy=not failures,
                observed_at=now,
                detail=",".join(failures),
            )
        )

    def refresh_strategies(self, *, now: datetime) -> bool:
        failures: list[str] = []
        for requirement in self._required_strategies:
            try:
                self._strategies.require_fresh(
                    strategy_id=requirement.strategy_id,
                    strategy_version=requirement.strategy_version,
                    now=now,
                    max_age_seconds=self._strategy_max_age_seconds,
                )
            except StrategyRuntimeError as exc:
                failures.append(
                    f"{requirement.strategy_id}:{type(exc).__name__}"
                )
        return self._health.observe(
            HealthObservation(
                component=HealthComponent.STRATEGY,
                healthy=not failures,
                observed_at=now,
                detail=",".join(failures),
            )
        )
