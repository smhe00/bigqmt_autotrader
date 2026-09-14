from bigqmt_autotrader.qmt import (
    QmtBrokerTokenCalibration,
    QmtEvent,
    broker_token_for,
    encode_transport_frame,
)
from bigqmt_autotrader.qmt.calibration_probe import build_report


FP = "sha256:" + "e" * 64


def qmt_event(sequence: int, event_type: str, payload: dict) -> QmtEvent:
    return QmtEvent.from_mapping(
        {
            "protocol_version": "0.2",
            "session_id": "calibration-session",
            "sequence": sequence,
            "timestamp_ms": 1_800_000_000_000 + sequence,
            "event_type": event_type,
            "source": "callback",
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "payload": payload,
        }
    )


def test_known_remark_correlates_order_and_deal_without_enabling_broker_evidence():
    calibration = QmtBrokerTokenCalibration()
    token = calibration.register(FP, "cid-cal-001")

    order = calibration.observe(
        qmt_event(
            1,
            "order",
            {
                "remark": token,
                "broker_order_id": "broker-1",
                "status_code": 50,
                "submit_status_code": 3,
                "filled_quantity": 0,
            },
        )
    )
    deal = calibration.observe(
        qmt_event(
            2,
            "deal",
            {
                "remark": token,
                "broker_order_id": "broker-1",
                "trade_id": "trade-1",
                "quantity": 100,
            },
        )
    )

    assert token == broker_token_for(FP, "cid-cal-001")
    assert order.disposition == "MATCHED_KNOWN_TOKEN"
    assert deal.disposition == "MATCHED_KNOWN_TOKEN"
    assert order.client_order_id == deal.client_order_id == "cid-cal-001"
    assert calibration.summary()["broker_evidence_mapping_enabled"] is False
    assert calibration.summary()["live_submit"] is False
    assert calibration.summary()["live_cancel"] is False


def test_unknown_or_malformed_remark_is_never_guessed():
    calibration = QmtBrokerTokenCalibration()
    calibration.register(FP, "cid-cal-001")

    unknown = calibration.observe(
        qmt_event(1, "order", {"remark": "BQ" + "f" * 20})
    )
    malformed = calibration.observe(qmt_event(2, "deal", {"remark": "cid-cal-001"}))
    missing = calibration.observe(qmt_event(3, "deal", {"remark": None}))

    assert unknown.disposition == "UNREGISTERED_TOKEN"
    assert malformed.disposition == "MALFORMED_REMARK"
    assert missing.disposition == "MISSING_REMARK"
    assert unknown.client_order_id is None
    assert malformed.client_order_id is None
    assert missing.client_order_id is None


def test_snapshot_rows_are_observed_without_becoming_broker_evidence():
    calibration = QmtBrokerTokenCalibration()
    token = calibration.register(FP, "cid-cal-001")
    snapshot = qmt_event(
        4,
        "snapshot",
        {
            "account": [],
            "positions": [],
            "orders": [{"remark": token, "broker_order_id": "broker-1"}],
            "deals": [{"remark": None, "trade_id": "trade-old"}],
            "query_errors": [],
        },
    )

    records = calibration.observe_snapshot(snapshot)

    assert len(records) == 2
    assert records[0].source == "snapshot"
    assert records[0].disposition == "MATCHED_KNOWN_TOKEN"
    assert records[1].disposition == "MISSING_REMARK"
    assert calibration.summary()["broker_evidence_mapping_enabled"] is False


def test_read_only_probe_scans_without_modifying_spool_files(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    token = broker_token_for(FP, "cid-cal-001")
    frame = {
        "protocol_version": "0.2",
        "session_id": "calibration-session",
        "sequence": 1,
        "timestamp_ms": 1_800_000_000_001,
        "event_type": "snapshot",
        "source": "active_query",
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "payload": {
            "account": [],
            "positions": [],
            "orders": [{"remark": token, "broker_order_id": "broker-1"}],
            "deals": [{"remark": None, "trade_id": "trade-old"}],
            "query_errors": [],
        },
    }
    path = processed / "event.json"
    path.write_bytes(encode_transport_frame(frame))
    before_bytes = path.read_bytes()
    before_stat = path.stat()

    report = build_report(
        spool_dir=tmp_path,
        expected_account_fingerprint=FP,
        client_order_ids=["cid-cal-001"],
        include_details=True,
    )

    after_stat = path.stat()
    assert report["mode"] == "READ_ONLY_CALIBRATION"
    assert report["event_frames_scanned"] == 1
    assert report["snapshot_order_deal_rows"] == 2
    assert report["dispositions"] == {
        "MATCHED_KNOWN_TOKEN": 1,
        "MISSING_REMARK": 1,
    }
    assert path.read_bytes() == before_bytes
    assert after_stat.st_mtime_ns == before_stat.st_mtime_ns
