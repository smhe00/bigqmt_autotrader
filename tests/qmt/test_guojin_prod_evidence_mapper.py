from bigqmt_autotrader.qmt import (
    GUOJIN_PRODUCTION_MAPPER_PROFILE,
    GuojinProductionEvidenceMapper,
    QmtEvent,
)


FP = "sha256:" + "a" * 64
CID = "prod-observe-001"


def event(sequence, event_type, payload, *, instance_id="guojin", source="callback"):
    return QmtEvent.from_mapping(
        {
            "protocol_version": "0.2",
            "session_id": "guojin-prod-session",
            "sequence": sequence,
            "timestamp_ms": 1_800_000_000_000 + sequence,
            "event_type": event_type,
            "source": source,
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "terminal_instance_id": instance_id,
            "payload": payload,
        }
    )


def order_payload(token):
    return {
        "symbol": "510300.SH",
        "remark": token,
        "order_ref": "prod-ref-1",
        "broker_order_id": "10001",
        "status_code": 50,
        "submit_status_code": 51,
        "original_quantity": 100,
        "filled_quantity": 0,
        "remaining_quantity": 100,
    }


def test_production_profile_is_explicitly_observe_only():
    mapper = GuojinProductionEvidenceMapper(account_fingerprint=FP)
    assert mapper.profile.name == GUOJIN_PRODUCTION_MAPPER_PROFILE
    assert mapper.profile.terminal_instance_id == "guojin"
    assert mapper.profile.evidence_enabled is False


def test_production_callback_identity_can_be_validated_but_never_emits_evidence():
    mapper = GuojinProductionEvidenceMapper(account_fingerprint=FP)
    token = mapper.register_order(client_order_id=CID, symbol="510300.SH", quantity=100)

    evidence = mapper(event(1, "order", order_payload(token)))

    assert evidence is None
    assert mapper.rejections[-1].reason == "PROFILE_EVIDENCE_DISABLED"


def test_production_profile_rejects_simulation_terminal():
    mapper = GuojinProductionEvidenceMapper(account_fingerprint=FP)
    token = mapper.register_order(client_order_id=CID, symbol="510300.SH", quantity=100)

    assert mapper(event(1, "order", order_payload(token), instance_id="guojin_sim")) is None
    assert mapper.rejections[-1].reason == "TERMINAL_INSTANCE_MISMATCH"


def test_production_active_query_is_observe_only_even_with_valid_route_identity():
    mapper = GuojinProductionEvidenceMapper(account_fingerprint=FP)
    token = mapper.register_order(client_order_id=CID, symbol="510300.SH", quantity=100)
    row = order_payload(token)
    row["route_account_type"] = "STOCK"
    row["route_account_fingerprint"] = FP
    snapshot = event(
        2,
        "snapshot",
        {
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "account": [],
            "positions": [],
            "orders": [row],
            "deals": [],
            "query_errors": [],
        },
        source="active_query",
    )

    batch = mapper.map_snapshot(snapshot)

    assert batch.evidence == ()
    assert batch.rejected_rows == 1
    assert mapper.rejections[-1].reason == "PROFILE_EVIDENCE_DISABLED"
