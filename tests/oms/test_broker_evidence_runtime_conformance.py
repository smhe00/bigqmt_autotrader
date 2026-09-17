from itertools import product

import pytest

from bigqmt_autotrader.domain import OrderStatus
from bigqmt_autotrader.oms import (
    BrokerEvidenceSourceKind,
    BrokerEvidenceType,
    BrokerEvidenceV1,
    OmsRepository,
)


BROKER_TERMINALS = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
}
CURRENT = (
    OrderStatus.UNKNOWN,
    OrderStatus.RECONCILING,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.MANUAL_REVIEW,
)
TARGETS = (
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
)


def reference_next(current: OrderStatus, target: OrderStatus) -> OrderStatus:
    if current is OrderStatus.MANUAL_REVIEW:
        return current
    if current in BROKER_TERMINALS:
        return current
    if target is OrderStatus.ACKNOWLEDGED and current is OrderStatus.PARTIALLY_FILLED:
        return current
    return target


NON_CONFLICT_CASES = tuple(
    (current, target)
    for current, target in product(CURRENT, TARGETS)
    if not (
        current in BROKER_TERMINALS
        and target in BROKER_TERMINALS
        and current is not target
    )
)


@pytest.mark.parametrize("current,target", NON_CONFLICT_CASES)
def test_runtime_broker_aggregator_matches_independent_finite_reference(current, target):
    actual = OmsRepository._aggregate_broker_status(current, target)
    assert actual.current is reference_next(current, target)


def _base(**overrides):
    values = {
        "source": "qmt-guojin",
        "source_kind": BrokerEvidenceSourceKind.ORDER_CALLBACK,
        "source_event_id": "session:1",
        "mapper_profile": "qmt-guojin-order-v1",
        "account_fingerprint": "sha256:" + "a" * 64,
        "client_order_id": "cid-runtime",
        "broker_token": "BQ" + "1" * 20,
        "broker_order_id": "4083",
        "order_ref": "ref-1",
        "trade_id": None,
        "evidence_type": BrokerEvidenceType.ORDER_ACCEPTED,
        "requested_status": OrderStatus.ACKNOWLEDGED,
        "filled_quantity": 0,
        "observed_at_ms": 1_700_000_000_000,
        "raw_payload_ref": "qmt://guojin/session/1",
        "raw_status": {"order_status": 50, "submit_status": 51},
    }
    values.update(overrides)
    return values


def test_runtime_model_enforces_source_authority_and_semantic_digest():
    with pytest.raises(ValueError, match="fill-only authority"):
        BrokerEvidenceV1.build(**_base(
            source_kind=BrokerEvidenceSourceKind.DEAL_CALLBACK,
            trade_id="trade-1",
            evidence_type=BrokerEvidenceType.ORDER_CANCELLED,
            requested_status=OrderStatus.CANCELLED,
        ))

    valid = BrokerEvidenceV1.build(**_base())
    changed = valid.to_mapping()
    changed["broker_order_id"] = "different"
    changed["source_kind"] = BrokerEvidenceSourceKind(changed["source_kind"])
    changed["evidence_type"] = BrokerEvidenceType(changed["evidence_type"])
    changed["requested_status"] = OrderStatus(changed["requested_status"])
    with pytest.raises(ValueError, match="semantic_digest"):
        BrokerEvidenceV1(**changed)
