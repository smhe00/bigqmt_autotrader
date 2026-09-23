from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, Side
from bigqmt_autotrader.qmt.guojin_sim_oms import (
    GuojinSimOmsRuntime,
    guojin_sim_oms_authorized,
)
from bigqmt_autotrader.qmt.instances import QmtInstance

FP = "sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702"
SESSION = "guojin-sim-core-boundary"


def instance(root, **overrides):
    values = dict(
        instance_id="guojin_sim",
        root=root,
        session_id=SESSION,
        account_fingerprint=FP,
        account_type="STOCK",
        bridge_build="p5-simulation-calibration-8",
        created_ms=1_800_000_000_000,
        execution_mode="SIMULATION_CALIBRATION",
        trading_enabled=True,
        live_submit=True,
        live_cancel=True,
        simulation_only=True,
    )
    values.update(overrides)
    return QmtInstance(**values)


def test_guojin_sim_core_submit_requires_no_risk_runtime_objects(tmp_path):
    now = datetime.now(timezone.utc)
    order = OrderIntent(
        client_order_id="sim-core-sgt",
        strategy_id="plain-client",
        strategy_version="v1",
        account_fingerprint=FP,
        symbol="00700.SGT",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("450.0"),
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        signal_id="manual",
        reason_code="CORE_DIRECT",
    )
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        result = runtime.execute_intent(order)
        assert result.authorization is not None
        assert result.authorization.accepted is True
        assert result.authorization.rule_version == "guojin-sim-accept-all-v1"
        assert result.dispatched is True
        assert result.command_id is not None
        assert result.status in {OrderStatus.SUBMITTING, OrderStatus.RECONCILING}
    finally:
        runtime.close()


def test_guojin_sim_core_boundary_does_not_relax_instance_authorization(tmp_path):
    assert not guojin_sim_oms_authorized(
        instance(tmp_path, instance_id="guojin", simulation_only=False),
        allow_simulation_mutation=True,
    )
    assert not guojin_sim_oms_authorized(
        instance(tmp_path, instance_id="galaxy", simulation_only=False),
        allow_simulation_mutation=True,
    )
