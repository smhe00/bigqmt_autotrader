from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.domain import OrderIntent, RiskReasonCode, Side
from bigqmt_autotrader.drivers import SimulatedDriver
from bigqmt_autotrader.oms import OfflineOms, OmsRepository, connect_database, initialize_database
from bigqmt_autotrader.risk import (
    AccountRiskSnapshot,
    RiskLevel,
    RiskPolicy,
    RiskSnapshot,
    RuntimeMode,
    SecurityRiskSnapshot,
    StrategyPolicy,
    StrategyRiskSnapshot,
    canonical_json,
    evaluate_risk,
    snapshot_hash,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 12, 10, 0, tzinfo=TZ)


def _intent(**changes):
    base = OrderIntent(
        client_order_id="cid-risk",
        strategy_id="strategyA",
        strategy_version="git:v1",
        account_fingerprint="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        symbol="000333.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("75.00"),
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
        signal_id="signal-risk",
        reason_code="TARGET_POSITION_REBALANCE",
    )
    return replace(base, **changes)


def _policy(**changes):
    strategy = StrategyPolicy(
        strategy_id="strategyA",
        allowed_versions=frozenset({"git:v1"}),
        allowed_symbols=frozenset({"000333.SZ", "600000.SH"}),
        max_gross_exposure=Decimal("300000"),
        max_daily_turnover=Decimal("500000"),
        max_position_count=10,
    )
    base = RiskPolicy(
        rule_version="p2-test-v1",
        expected_account_fingerprint="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
        strategy=strategy,
    )
    return replace(base, **changes)


def _snapshot(**changes):
    account = AccountRiskSnapshot(
        account_fingerprint="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        available_cash=Decimal("500000"),
        gross_exposure=Decimal("300000"),
        daily_pnl=Decimal("1000"),
        daily_turnover=Decimal("100000"),
        daily_order_count=5,
        daily_cancel_count=2,
        observed_at=NOW - timedelta(seconds=1),
    )
    strategy = StrategyRiskSnapshot(
        strategy_id="strategyA",
        strategy_version="git:v1",
        gross_exposure=Decimal("100000"),
        security_gross_exposure=Decimal("50000"),
        daily_turnover=Decimal("50000"),
        position_count=3,
        heartbeat_at=NOW - timedelta(seconds=1),
    )
    security = SecurityRiskSnapshot(
        symbol="000333.SZ",
        tick_size=Decimal("0.01"),
        lower_price_limit=Decimal("67.50"),
        upper_price_limit=Decimal("82.50"),
        reference_price=Decimal("75.00"),
        buy_lot_size=100,
        sell_lot_size=100,
        sellable_quantity=1000,
        gross_exposure=Decimal("50000"),
        observed_at=NOW - timedelta(seconds=1),
    )
    base = RiskSnapshot(
        mode=RuntimeMode.SIMULATION,
        database_healthy=True,
        oms_healthy=True,
        leader_held=True,
        reconciliation_complete=True,
        qmt_healthy=False,
        market_open=True,
        global_ambiguity_block=False,
        blocked_symbols=frozenset(),
        account=account,
        strategy=strategy,
        security=security,
    )
    return replace(base, **changes)


def _rules(evaluation):
    return [finding.rule_id for finding in evaluation.findings]


def test_baseline_simulation_order_is_accepted():
    evaluation = evaluate_risk(_intent(), _snapshot(), _policy(), now=NOW)
    assert evaluation.decision.accepted is True
    assert evaluation.decision.reason_code is RiskReasonCode.OK
    assert evaluation.findings == ()
    assert evaluation.decision.snapshot_hash == snapshot_hash(_snapshot())


def test_primary_reason_is_deterministic_global_precedence():
    snapshot = replace(
        _snapshot(),
        database_healthy=False,
        leader_held=False,
        market_open=False,
    )
    evaluation = evaluate_risk(_intent(), snapshot, _policy(), now=NOW)
    assert evaluation.decision.accepted is False
    assert evaluation.decision.reason_code is RiskReasonCode.DATABASE_UNHEALTHY
    assert _rules(evaluation)[:3] == [
        "GLOBAL_DATABASE_HEALTH",
        "GLOBAL_LEADER_HELD",
        "GLOBAL_MARKET_OPEN",
    ]


@pytest.mark.parametrize(
    ("snapshot", "rule_id", "reason"),
    [
        (replace(_snapshot(), oms_healthy=False), "GLOBAL_OMS_HEALTH", RiskReasonCode.DATA_STALE),
        (replace(_snapshot(), leader_held=False), "GLOBAL_LEADER_HELD", RiskReasonCode.LEADER_NOT_HELD),
        (
            replace(_snapshot(), reconciliation_complete=False),
            "GLOBAL_RECONCILIATION_COMPLETE",
            RiskReasonCode.DATA_STALE,
        ),
        (
            replace(_snapshot(), mode=RuntimeMode.LIVE_ARMED),
            "GLOBAL_RUNTIME_MODE",
            RiskReasonCode.MODE_NOT_ARMED,
        ),
        (
            replace(_snapshot(), global_ambiguity_block=True),
            "GLOBAL_BLOCKING_AMBIGUITY",
            RiskReasonCode.UNKNOWN_ORDER,
        ),
        (
            replace(_snapshot(), market_open=False),
            "GLOBAL_MARKET_OPEN",
            RiskReasonCode.MARKET_CLOSED,
        ),
    ],
)
def test_global_fail_closed_rules(snapshot, rule_id, reason):
    evaluation = evaluate_risk(_intent(), snapshot, _policy(), now=NOW)
    assert evaluation.decision.reason_code is reason
    assert evaluation.findings[0].rule_id == rule_id


def test_qmt_health_only_blocks_when_policy_requires_it():
    accepted = evaluate_risk(_intent(), _snapshot(qmt_healthy=False), _policy(), now=NOW)
    assert accepted.decision.accepted

    required = _policy(require_qmt_healthy=True)
    rejected = evaluate_risk(_intent(), _snapshot(qmt_healthy=False), required, now=NOW)
    assert rejected.findings[0].rule_id == "GLOBAL_QMT_HEALTH"


@pytest.mark.parametrize(
    ("account", "expected_rule"),
    [
        (replace(_snapshot().account, daily_pnl=Decimal("-50000.01")), "GLOBAL_DAILY_LOSS_LIMIT"),
        (replace(_snapshot().account, daily_turnover=Decimal("995000")), "GLOBAL_DAILY_TURNOVER_LIMIT"),
        (replace(_snapshot().account, daily_order_count=100), "GLOBAL_DAILY_ORDER_LIMIT"),
        (replace(_snapshot().account, daily_cancel_count=51), "GLOBAL_DAILY_CANCEL_LIMIT"),
    ],
)
def test_global_activity_limits(account, expected_rule):
    evaluation = evaluate_risk(_intent(), _snapshot(account=account), _policy(), now=NOW)
    assert expected_rule in _rules(evaluation)


def test_account_fingerprint_mismatch_rejects():
    account = replace(_snapshot().account, account_fingerprint="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    evaluation = evaluate_risk(_intent(), _snapshot(account=account), _policy(), now=NOW)
    assert "ACCOUNT_FINGERPRINT_MATCH" in _rules(evaluation)
    finding = next(x for x in evaluation.findings if x.rule_id == "ACCOUNT_FINGERPRINT_MATCH")
    assert finding.reason_code is RiskReasonCode.ACCOUNT_MISMATCH


def test_account_future_or_stale_snapshot_rejects():
    for observed_at in (NOW - timedelta(seconds=31), NOW + timedelta(microseconds=1)):
        account = replace(_snapshot().account, observed_at=observed_at)
        evaluation = evaluate_risk(_intent(), _snapshot(account=account), _policy(), now=NOW)
        assert "ACCOUNT_SNAPSHOT_FRESHNESS" in _rules(evaluation)


def test_account_cross_snapshot_exposure_contradictions_reject():
    security = replace(_snapshot().security, gross_exposure=Decimal("400000"))
    strategy = replace(
        _snapshot().strategy,
        gross_exposure=Decimal("350000"),
        security_gross_exposure=Decimal("50000"),
    )
    snapshot = _snapshot(security=security, strategy=strategy)
    rules = _rules(evaluate_risk(_intent(), snapshot, _policy(), now=NOW))
    assert "ACCOUNT_SNAPSHOT_CONSISTENCY" in rules
    assert "ACCOUNT_STRATEGY_EXPOSURE_CONSISTENCY" in rules


def test_projected_account_exposure_blocks_buy_but_not_risk_reducing_sell():
    policy = _policy(max_account_gross_exposure=Decimal("300000"))
    buy = evaluate_risk(_intent(), _snapshot(), policy, now=NOW)
    assert "ACCOUNT_PROJECTED_EXPOSURE" in _rules(buy)

    sell_intent = _intent(side=Side.SELL)
    sell = evaluate_risk(sell_intent, _snapshot(), policy, now=NOW)
    assert "ACCOUNT_PROJECTED_EXPOSURE" not in _rules(sell)


def test_strategy_identity_version_and_universe_are_fail_closed():
    bad_version = _intent(strategy_version="git:v2")
    evaluation = evaluate_risk(bad_version, _snapshot(), _policy(), now=NOW)
    assert "STRATEGY_ID_VERSION_ALLOWLIST" in _rules(evaluation)

    outside = _intent(symbol="300001.SZ")
    security = replace(_snapshot().security, symbol="300001.SZ")
    evaluation = evaluate_risk(outside, _snapshot(security=security), _policy(), now=NOW)
    assert "STRATEGY_SYMBOL_UNIVERSE" in _rules(evaluation)


def test_strategy_staleness_exposure_turnover_and_position_limits():
    stale = replace(_snapshot().strategy, heartbeat_at=NOW - timedelta(seconds=31))
    assert "STRATEGY_HEARTBEAT_FRESHNESS" in _rules(
        evaluate_risk(_intent(), _snapshot(strategy=stale), _policy(), now=NOW)
    )

    exposure_policy = _policy(
        strategy=replace(_policy().strategy, max_gross_exposure=Decimal("105000"))
    )
    assert "STRATEGY_PROJECTED_EXPOSURE" in _rules(
        evaluate_risk(_intent(), _snapshot(), exposure_policy, now=NOW)
    )

    turnover_policy = _policy(
        strategy=replace(_policy().strategy, max_daily_turnover=Decimal("57000"))
    )
    assert "STRATEGY_DAILY_TURNOVER_LIMIT" in _rules(
        evaluate_risk(_intent(), _snapshot(), turnover_policy, now=NOW)
    )

    zero_symbol = replace(
        _snapshot().strategy,
        security_gross_exposure=Decimal("0"),
        position_count=3,
    )
    count_policy = _policy(strategy=replace(_policy().strategy, max_position_count=3))
    assert "STRATEGY_POSITION_COUNT_LIMIT" in _rules(
        evaluate_risk(_intent(), _snapshot(strategy=zero_symbol), count_policy, now=NOW)
    )


def test_expired_intent_and_market_snapshot_staleness_reject():
    expired = _intent(expires_at=NOW)
    evaluation = evaluate_risk(expired, _snapshot(), _policy(), now=NOW)
    assert "ORDER_INTENT_EXPIRY" in _rules(evaluation)

    security = replace(_snapshot().security, observed_at=NOW - timedelta(seconds=6))
    evaluation = evaluate_risk(_intent(), _snapshot(security=security), _policy(), now=NOW)
    assert "ORDER_MARKET_DATA_FRESHNESS" in _rules(evaluation)


def test_security_identity_suffix_and_ambiguity_rules():
    mismatch = replace(_snapshot().security, symbol="600000.SH")
    evaluation = evaluate_risk(_intent(), _snapshot(security=mismatch), _policy(), now=NOW)
    assert "ORDER_SECURITY_SUPPORTED" in _rules(evaluation)

    unsupported = _intent(symbol="000333.HK")
    security = replace(_snapshot().security, symbol="000333.HK")
    evaluation = evaluate_risk(unsupported, _snapshot(security=security), _policy(), now=NOW)
    assert "ORDER_SECURITY_SUPPORTED" in _rules(evaluation)

    blocked = _snapshot(blocked_symbols=frozenset({"000333.SZ"}))
    evaluation = evaluate_risk(_intent(), blocked, _policy(), now=NOW)
    assert "ORDER_SYMBOL_AMBIGUITY" in _rules(evaluation)


def test_tick_price_band_and_reference_deviation_rules():
    bad_tick = _intent(limit_price=Decimal("75.005"))
    evaluation = evaluate_risk(bad_tick, _snapshot(), _policy(), now=NOW)
    assert "ORDER_TICK_SIZE" in _rules(evaluation)

    out_of_band = _intent(limit_price=Decimal("82.51"))
    evaluation = evaluate_risk(out_of_band, _snapshot(), _policy(), now=NOW)
    assert "ORDER_PRICE_BAND" in _rules(evaluation)

    wide_band = replace(
        _snapshot().security,
        lower_price_limit=Decimal("50"),
        upper_price_limit=Decimal("100"),
    )
    deviation = _intent(limit_price=Decimal("83.00"))
    evaluation = evaluate_risk(deviation, _snapshot(security=wide_band), _policy(), now=NOW)
    assert "ORDER_REFERENCE_PRICE_DEVIATION" in _rules(evaluation)


def test_lot_notional_and_security_exposure_rules():
    odd_lot = _intent(quantity=150)
    evaluation = evaluate_risk(odd_lot, _snapshot(), _policy(), now=NOW)
    assert "ORDER_LOT_SIZE" in _rules(evaluation)

    notional_policy = _policy(max_order_notional=Decimal("7000"))
    evaluation = evaluate_risk(_intent(), _snapshot(), notional_policy, now=NOW)
    assert "ORDER_NOTIONAL_LIMIT" in _rules(evaluation)

    security_policy = _policy(max_security_gross_exposure=Decimal("55000"))
    evaluation = evaluate_risk(_intent(), _snapshot(), security_policy, now=NOW)
    assert "ORDER_SECURITY_EXPOSURE_LIMIT" in _rules(evaluation)


def test_buy_cash_and_sellable_quantity_rules():
    low_cash = replace(_snapshot().account, available_cash=Decimal("17000"))
    evaluation = evaluate_risk(_intent(), _snapshot(account=low_cash), _policy(), now=NOW)
    assert "ORDER_BUY_CASH_WITH_FEE_BUFFER" in _rules(evaluation)

    sell = _intent(side=Side.SELL, quantity=200)
    security = replace(_snapshot().security, sellable_quantity=100)
    evaluation = evaluate_risk(sell, _snapshot(security=security), _policy(), now=NOW)
    assert "ORDER_SELLABLE_QUANTITY" in _rules(evaluation)


def test_sell_uses_explicit_sell_lot_rule():
    sell = _intent(side=Side.SELL, quantity=50)
    security = replace(_snapshot().security, sell_lot_size=1, sellable_quantity=50)
    evaluation = evaluate_risk(sell, _snapshot(security=security), _policy(), now=NOW)
    assert "ORDER_LOT_SIZE" not in _rules(evaluation)


def test_snapshot_hash_is_stable_for_equivalent_frozenset_order():
    a = _snapshot(blocked_symbols=frozenset(["600000.SH", "000333.SZ"]))
    b = _snapshot(blocked_symbols=frozenset(["000333.SZ", "600000.SH"]))
    assert canonical_json(a) == canonical_json(b)
    assert snapshot_hash(a) == snapshot_hash(b)
    assert snapshot_hash(a).startswith("sha256:")


def test_risk_models_reject_binary_float():
    with pytest.raises(TypeError, match="binary float"):
        _policy(fee_buffer_rate=0.002)  # type: ignore[arg-type]


def test_same_inputs_produce_same_findings_and_hash():
    first = evaluate_risk(_intent(), _snapshot(), _policy(), now=NOW)
    second = evaluate_risk(_intent(), _snapshot(), _policy(), now=NOW)
    assert first == second


def test_rejected_risk_decision_never_reaches_simulated_broker(tmp_path):
    conn = connect_database(tmp_path / "oms.sqlite3")
    initialize_database(conn)
    repo = OmsRepository(conn)
    driver = SimulatedDriver()
    oms = OfflineOms(repo, driver)
    oms.recover()

    snapshot = replace(_snapshot(), mode=RuntimeMode.DISABLED)
    evaluation = evaluate_risk(_intent(), snapshot, _policy(), now=NOW)
    assert evaluation.decision.accepted is False

    result = oms.submit_intent(_intent(), evaluation.decision)
    assert result.status.value == "RISK_REJECTED"
    assert driver.submit_call_count("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-risk") == 0
