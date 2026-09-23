from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from bigqmt_autotrader.domain import OrderIntent
from bigqmt_autotrader.operations import OperationsControl, OperationsStatus
from bigqmt_autotrader.risk import (
    RiskEvaluation,
    RiskPolicy,
    RiskSnapshot,
    SecurityRiskReference,
    evaluate_risk,
)

from .risk_runtime import AccountState, RuntimeRiskAssembler, StrategyState


@dataclass(frozen=True)
class RuntimeIntentEvaluation:
    operations: OperationsStatus
    snapshot: RiskSnapshot
    risk: RiskEvaluation


class ExecutionRuntimeCoordinator:
    """Production-facing pre-submit decision coordinator.

    This class intentionally has no OMS repository, QMT spool, passorder or
    cancel dependency. It can decide whether an intent is eligible, but cannot
    create a broker side effect.
    """

    def __init__(
        self,
        *,
        operations: OperationsControl,
        risk_assembler: RuntimeRiskAssembler,
        policy: RiskPolicy,
        health_max_age_seconds: int,
    ) -> None:
        if not isinstance(operations, OperationsControl):
            raise TypeError("operations must be OperationsControl")
        if not isinstance(risk_assembler, RuntimeRiskAssembler):
            raise TypeError("risk_assembler must be RuntimeRiskAssembler")
        if not isinstance(policy, RiskPolicy):
            raise TypeError("policy must be RiskPolicy")
        if (
            isinstance(health_max_age_seconds, bool)
            or not isinstance(health_max_age_seconds, int)
            or health_max_age_seconds <= 0
        ):
            raise ValueError("health_max_age_seconds must be a positive integer")
        self._operations = operations
        self._risk_assembler = risk_assembler
        self._policy = policy
        self._health_max_age_seconds = health_max_age_seconds

    def evaluate_intent(
        self,
        intent: OrderIntent,
        *,
        trading_date: date,
        now: datetime,
        market_open: bool,
        global_ambiguity_block: bool,
        blocked_symbols: frozenset[str],
        account: AccountState,
        strategy: StrategyState,
        security: SecurityRiskReference,
    ) -> RuntimeIntentEvaluation:
        if not isinstance(intent, OrderIntent):
            raise TypeError("intent must be OrderIntent")
        operations = self._operations.status(
            now=now,
            max_age_seconds=self._health_max_age_seconds,
        )
        snapshot = self._risk_assembler.build(
            policy=self._policy,
            trading_date=trading_date,
            now=now,
            mode=operations.mode,
            health=operations.health,
            market_open=market_open,
            global_ambiguity_block=global_ambiguity_block,
            blocked_symbols=blocked_symbols,
            account=account,
            strategy=strategy,
            security=security,
        )
        risk = evaluate_risk(intent, snapshot, self._policy, now=now)
        return RuntimeIntentEvaluation(
            operations=operations,
            snapshot=snapshot,
            risk=risk,
        )
