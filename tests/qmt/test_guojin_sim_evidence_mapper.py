from __future__ import annotations

from copy import deepcopy

import pytest

from bigqmt_autotrader.domain import OrderStatus
from bigqmt_autotrader.oms import BrokerEvidenceSourceKind, BrokerEvidenceType
from bigqmt_autotrader.qmt import (
    GuojinSimEvidenceMapper,
    QmtEvent,
    QmtHostIngestion,
    QmtIngressBuffer,
    encode_transport_frame,
)


FP = "sha256:" + "f" * 64
CID = "simcal-guojin-mapper-001"


def event(
    sequence: int,
    event_type: str,
    payload: dict,
    *,
    source: str | None = None,
    instance_id: str = "guojin_sim",
    account_fingerprint: str = FP,
) -> QmtEvent:
    return QmtEvent.from_mapping(
        {
            "protocol_version": "0.2",
            "session_id": "guojin-sim-session",
            "sequence": sequence,
            "timestamp_ms": 1_800_000_000_000 + sequence,
            "event_type": event_type,
            "source": source or ("active_query" if event_type == "snapshot" else "callback"),
            "account_fingerprint": account_fingerprint,
            "account_type": "STOCK",
            "terminal_instance_id": instance_id,
            "payload": payload,
        }
    )


def order_payload(token: str, **overrides) -> dict:
    value = {
        "symbol": "510300.SH",
        "remark": token,
        "order_ref": "ref-1",
        "broker_order_id": "4083",
        "status_code": 50,
        "submit_status_code": 51,
        "original_quantity": 100,
        "filled_quantity": 0,
        "remaining_quantity": 100,
    }
    value.update(overrides)
    return value


def snapshot_payload(*, orders: list, deals: list) -> dict:
    return {
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "account": [],
        "positions": [],
        "orders": orders,
        "deals": deals,
        "query_errors": [],
    }


def mapper() -> tuple[GuojinSimEvidenceMapper, str]:
    value = GuojinSimEvidenceMapper(account_fingerprint=FP)
    return value, value.register_order(
        client_order_id=CID, symbol="510300.SH", quantity=100
    )


@pytest.mark.parametrize(
    ("status", "filled", "broker_order_id", "evidence_type", "requested_status"),
    [
        (50, 0, "4083", BrokerEvidenceType.ORDER_ACCEPTED, OrderStatus.ACKNOWLEDGED),
        (54, 0, "4083", BrokerEvidenceType.ORDER_CANCELLED, OrderStatus.CANCELLED),
        (56, 100, "4083", BrokerEvidenceType.FULL_FILL, OrderStatus.FILLED),
        (57, 0, "", BrokerEvidenceType.ORDER_REJECTED, OrderStatus.REJECTED),
    ],
)
def test_calibrated_guojin_order_statuses_map_to_strict_broker_evidence(
    status, filled, broker_order_id, evidence_type, requested_status
):
    value, token = mapper()
    payload = order_payload(
        token,
        status_code=status,
        broker_order_id=broker_order_id,
        filled_quantity=filled,
        remaining_quantity=0 if status in {56, 57} else 100,
    )

    evidence = value(event(1, "order", payload))

    assert evidence is not None
    assert evidence.mapper_profile == "qmt-guojin-sim-20260917-v1"
    assert evidence.source_kind is BrokerEvidenceSourceKind.ORDER_CALLBACK
    assert evidence.evidence_type is evidence_type
    assert evidence.requested_status is requested_status
    assert evidence.filled_quantity == filled
    assert evidence.client_order_id == CID
    assert evidence.broker_token == token
    assert value.rejections == []


def test_initial_status_50_without_broker_id_is_not_broker_ack():
    value, token = mapper()

    evidence = value(
        event(
            1,
            "order",
            order_payload(token, broker_order_id="", remaining_quantity=0),
        )
    )

    assert evidence is None
    assert value.rejections[-1].reason == "ORDER_ACCEPTED_NOT_SETTLED"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"status_code": 55}, "UNKNOWN_ORDER_STATUS"),
        ({"submit_status_code": 3}, "UNCALIBRATED_ORDER_SHAPE"),
        ({"original_quantity": 200}, "UNCALIBRATED_ORDER_SHAPE"),
        ({"remark": None}, "MISSING_OR_MALFORMED_TOKEN"),
        ({"remark": "client-order-id"}, "MISSING_OR_MALFORMED_TOKEN"),
        ({"remark": "BQ" + "0" * 20}, "UNREGISTERED_TOKEN"),
        ({"symbol": "000001.SZ"}, "SYMBOL_MISMATCH"),
    ],
)
def test_unknown_shape_or_token_fails_closed(overrides, reason):
    value, token = mapper()

    evidence = value(event(1, "order", order_payload(token, **overrides)))

    assert evidence is None
    assert value.rejections[-1].reason == reason


def test_mapper_is_hard_pinned_to_guojin_sim_and_account():
    value, token = mapper()

    assert value(event(1, "order", order_payload(token), instance_id="guojin")) is None
    assert value.rejections[-1].reason == "TERMINAL_INSTANCE_MISMATCH"
    assert (
        value(
            event(
                2,
                "order",
                order_payload(token),
                account_fingerprint="sha256:" + "e" * 64,
            )
        )
        is None
    )
    assert value.rejections[-1].reason == "ACCOUNT_MISMATCH"


def test_broker_order_id_conflict_fails_closed():
    value, token = mapper()
    assert value(event(1, "order", order_payload(token))) is not None

    evidence = value(event(2, "order", order_payload(token, broker_order_id="9999")))

    assert evidence is None
    assert value.rejections[-1].reason == "BROKER_ORDER_ID_CONFLICT"


def test_deal_evidence_uses_deduplicated_cumulative_fill():
    value = GuojinSimEvidenceMapper(account_fingerprint=FP)
    token = value.register_order(client_order_id=CID, symbol="510300.SH", quantity=100)
    deal_1 = {
        "symbol": "510300.SH",
        "remark": token,
        "broker_order_id": "4083",
        "trade_id": "trade-1",
        "quantity": 40,
    }
    deal_2 = dict(deal_1, trade_id="trade-2", quantity=60)

    first = value(event(1, "deal", deal_1))
    duplicate = value(event(2, "deal", deepcopy(deal_1)))
    second = value(event(3, "deal", deal_2))

    assert first is not None and first.evidence_type is BrokerEvidenceType.PARTIAL_FILL
    assert first.filled_quantity == 40
    assert duplicate is not None and duplicate.filled_quantity == 40
    assert second is not None and second.evidence_type is BrokerEvidenceType.FULL_FILL
    assert second.filled_quantity == 100


def test_trade_conflict_and_overfill_do_not_pollute_cumulative_ledger():
    value, token = mapper()
    base = {
        "symbol": "510300.SH",
        "remark": token,
        "broker_order_id": "4083",
        "trade_id": "trade-1",
        "quantity": 60,
    }
    assert value(event(1, "deal", base)).filled_quantity == 60
    assert value(event(2, "deal", dict(base, quantity=70))) is None
    assert value.rejections[-1].reason == "TRADE_ID_CONFLICT"
    assert value(event(3, "deal", dict(base, trade_id="trade-2", quantity=50))) is None
    assert value.rejections[-1].reason == "CUMULATIVE_FILL_EXCEEDS_ORDER"
    final = value(event(4, "deal", dict(base, trade_id="trade-2", quantity=40)))
    assert final is not None and final.filled_quantity == 100


def test_active_query_snapshot_maps_known_rows_and_counts_quarantine_rows():
    value, token = mapper()
    snapshot = event(
        9,
        "snapshot",
        snapshot_payload(
            orders=[
                order_payload(token, status_code=54),
                order_payload("BQ" + "0" * 20),
            ],
            deals=[],
        ),
    )

    batch = value.map_snapshot(snapshot)

    assert len(batch.evidence) == 1
    assert batch.rejected_rows == 1
    assert batch.evidence[0].source_kind is BrokerEvidenceSourceKind.ACTIVE_ORDER_QUERY
    assert batch.evidence[0].source_event_id.endswith("/order/0")
    assert value.rejections[-1].reason == "UNREGISTERED_TOKEN"


class _Sink:
    def __init__(self) -> None:
        self.evidence = []

    def ingest_broker_evidence(self, evidence) -> None:
        self.evidence.append(evidence)


def test_host_ingests_known_active_query_evidence_and_quarantines_unknown_rows():
    value, token = mapper()
    sink = _Sink()
    host = QmtHostIngestion(
        evidence_sink=sink,
        evidence_mapper=value,
        snapshot_evidence_mapper=value.map_snapshot,
    )
    ingress = QmtIngressBuffer(
        expected_account_fingerprint=FP,
        expected_terminal_instance_id="guojin_sim",
    )
    frame = encode_transport_frame(
        event(
            10,
            "snapshot",
            snapshot_payload(
                orders=[
                    order_payload(token, status_code=54),
                    order_payload("BQ" + "0" * 20),
                ],
                deals=[],
            ),
        ).__dict__
    )

    result = host.handle(ingress.ingest_frame(frame))

    assert result.evidence_ingested is True
    assert result.quarantined is True
    assert host.read_model.healthy is True
    assert len(host.quarantine) == 1
    assert len(sink.evidence) == 1


def test_registration_is_idempotent_but_quantity_conflict_is_rejected():
    value, token = mapper()
    assert value.register_order(
        client_order_id=CID, symbol="510300.SH", quantity=100
    ) == token
    with pytest.raises(ValueError, match="conflicting"):
        value.register_order(client_order_id=CID, symbol="510300.SH", quantity=200)
