from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3

from bigqmt_autotrader.market_data import (
    MarketDataService,
    QmtMarketDataAdapter,
)
from bigqmt_autotrader.oms import (
    SUPPORTED_SCHEMA_VERSION,
    current_schema_version,
)
from bigqmt_autotrader.operations import (
    HealthRegistry,
    OperationsControl,
    OperationsTelemetry,
    RuntimeModeController,
)
from bigqmt_autotrader.risk import DailyRiskLedger, RiskPolicy
from bigqmt_autotrader.strategy_api import StrategyRuntimeService

from .coordinator import ExecutionRuntimeCoordinator
from .deployment import (
    DeploymentGuard,
    DeploymentMismatch,
    ObservedDeployment,
    ReleaseManifest,
)
from .health_sync import RuntimeHealthSynchronizer, StrategyHealthRequirement
from .risk_runtime import RuntimeRiskAssembler
from .supervisor import RuntimeSupervisor


@dataclass(frozen=True)
class RuntimeServiceBundle:
    market_data: MarketDataService
    strategies: StrategyRuntimeService
    daily_risk: DailyRiskLedger
    health: HealthRegistry
    modes: RuntimeModeController
    operations: OperationsControl
    telemetry: OperationsTelemetry
    supervisor: RuntimeSupervisor
    qmt_market_data: QmtMarketDataAdapter
    health_sync: RuntimeHealthSynchronizer
    risk_assembler: RuntimeRiskAssembler
    coordinator: ExecutionRuntimeCoordinator


def _deployment_preflight(
    conn: sqlite3.Connection,
    *,
    expected: ReleaseManifest,
    observed: ObservedDeployment,
) -> None:
    errors: list[str] = []
    if expected.schema_version != SUPPORTED_SCHEMA_VERSION:
        errors.append("RELEASE_SCHEMA_DOES_NOT_MATCH_BINARY_CONSTANT")
    actual_schema = current_schema_version(conn)
    if actual_schema != observed.database_schema_version:
        errors.append("OBSERVED_DATABASE_SCHEMA_MISMATCH")
    if actual_schema != SUPPORTED_SCHEMA_VERSION:
        errors.append("DATABASE_SCHEMA_DOES_NOT_MATCH_BINARY_CONSTANT")
    if errors:
        raise DeploymentMismatch(tuple(errors))
    DeploymentGuard.assert_compatible(expected, observed)


def bootstrap_runtime_services(
    conn: sqlite3.Connection,
    *,
    expected_release: ReleaseManifest,
    observed_deployment: ObservedDeployment,
    runtime_session_id: str,
    started_at: datetime,
    account_fingerprint: str,
    policy: RiskPolicy,
    required_symbols: tuple[str, ...],
    required_strategies: tuple[StrategyHealthRequirement, ...],
    health_max_age_seconds: int,
) -> RuntimeServiceBundle:
    """Construct production runtime services after an immutable deployment gate.

    This function deliberately performs no schema migration and creates no QMT
    broker mutation surface. The returned runtime always starts DISABLED.
    """
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(policy, RiskPolicy):
        raise TypeError("policy must be RiskPolicy")
    if not isinstance(account_fingerprint, str) or not account_fingerprint:
        raise ValueError("account_fingerprint must be non-empty")
    if policy.expected_account_fingerprint != account_fingerprint:
        raise ValueError("policy account fingerprint does not match runtime account")
    if not isinstance(required_symbols, tuple) or not required_symbols:
        raise ValueError("required_symbols must be a non-empty tuple")
    if not policy.strategy.allowed_symbols.issubset(set(required_symbols)):
        raise ValueError(
            "required_symbols must cover the complete strategy symbol allow-list"
        )
    if (
        not isinstance(required_strategies, tuple)
        or not required_strategies
    ):
        raise ValueError("required_strategies must be non-empty")
    if not any(
        item.strategy_id == policy.strategy.strategy_id
        and item.strategy_version in policy.strategy.allowed_versions
        for item in required_strategies
    ):
        raise ValueError(
            "required_strategies must cover the configured strategy identity"
        )
    if (
        isinstance(health_max_age_seconds, bool)
        or not isinstance(health_max_age_seconds, int)
        or health_max_age_seconds <= 0
    ):
        raise ValueError("health_max_age_seconds must be a positive integer")

    # Deployment/schema identity must be proven before RuntimeModeController
    # writes even the startup DISABLED audit row.
    _deployment_preflight(
        conn,
        expected=expected_release,
        observed=observed_deployment,
    )

    market_data = MarketDataService()
    strategies = StrategyRuntimeService()
    daily_risk = DailyRiskLedger(conn)
    health = HealthRegistry()
    modes = RuntimeModeController(
        conn,
        runtime_session_id=runtime_session_id,
        started_at=started_at,
    )
    operations = OperationsControl(modes=modes, health=health)
    telemetry = OperationsTelemetry()
    supervisor = RuntimeSupervisor(
        operations=operations,
        telemetry=telemetry,
        health_max_age_seconds=health_max_age_seconds,
    )
    qmt_market_data = QmtMarketDataAdapter(
        market_data=market_data,
        expected_account_fingerprint=account_fingerprint,
        expected_terminal_instance_id=expected_release.terminal_instance_id,
    )
    health_sync = RuntimeHealthSynchronizer(
        health=health,
        market_data=market_data,
        strategies=strategies,
        required_symbols=required_symbols,
        required_strategies=required_strategies,
        market_max_age_seconds=policy.market_max_age_seconds,
        strategy_max_age_seconds=policy.strategy_max_age_seconds,
    )
    risk_assembler = RuntimeRiskAssembler(
        market_data=market_data,
        daily_risk=daily_risk,
        strategies=strategies,
    )
    coordinator = ExecutionRuntimeCoordinator(
        operations=operations,
        risk_assembler=risk_assembler,
        policy=policy,
        health_max_age_seconds=health_max_age_seconds,
    )

    return RuntimeServiceBundle(
        market_data=market_data,
        strategies=strategies,
        daily_risk=daily_risk,
        health=health,
        modes=modes,
        operations=operations,
        telemetry=telemetry,
        supervisor=supervisor,
        qmt_market_data=qmt_market_data,
        health_sync=health_sync,
        risk_assembler=risk_assembler,
        coordinator=coordinator,
    )
