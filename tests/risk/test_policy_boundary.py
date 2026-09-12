from dataclasses import replace
from decimal import Decimal

import pytest

from bigqmt_autotrader.risk import RiskPolicy, RuntimeMode, StrategyPolicy


def _policy(**changes):
    base = RiskPolicy(
        rule_version="p2-policy-boundary",
        expected_account_fingerprint="account-A",
        permitted_execution_modes=frozenset({RuntimeMode.SIMULATION}),
        require_qmt_healthy=False,
        account_max_age_seconds=30,
        strategy_max_age_seconds=30,
        market_max_age_seconds=5,
        min_cash_buffer=Decimal("10000"),
        fee_buffer_rate=Decimal("0.002"),
        max_account_gross_exposure=Decimal("800000"),
        max_daily_loss_abs=Decimal("50000"),
        max_daily_turnover=Decimal("1000000"),
        max_daily_orders=100,
        max_daily_cancels=50,
        max_order_notional=Decimal("100000"),
        max_security_gross_exposure=Decimal("200000"),
        max_price_deviation_rate=Decimal("0.10"),
        strategy=StrategyPolicy(
            strategy_id="strategyA",
            allowed_versions=frozenset({"git:v1"}),
            allowed_symbols=frozenset({"000333.SZ"}),
            max_gross_exposure=Decimal("300000"),
            max_daily_turnover=Decimal("500000"),
            max_position_count=10,
        ),
    )
    return replace(base, **changes)


def test_p2_policy_permits_simulation_only():
    policy = _policy()
    assert policy.permitted_execution_modes == frozenset({RuntimeMode.SIMULATION})


@pytest.mark.parametrize(
    "modes",
    [
        frozenset({RuntimeMode.LIVE_CANARY}),
        frozenset({RuntimeMode.LIVE_ARMED}),
        frozenset({RuntimeMode.SIMULATION, RuntimeMode.LIVE_CANARY}),
        frozenset({RuntimeMode.SHADOW}),
    ],
)
def test_p2_policy_rejects_non_simulation_execution_authority(modes):
    with pytest.raises(ValueError, match="P2 policy may permit SIMULATION only"):
        _policy(permitted_execution_modes=modes)
