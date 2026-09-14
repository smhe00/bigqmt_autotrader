from bigqmt_autotrader.qmt import (
    QmtEvent,
    broker_token_from_remark,
    order_deal_calibration_record,
)


FP = "sha256:" + "a" * 64
TOKEN = "BQ" + "1" * 20


def make_event(event_type: str, payload: dict) -> QmtEvent:
    return QmtEvent.from_mapping(
        {
            "protocol_version": "0.2",
            "session_id": "session-calibration",
            "sequence": 7,
            "timestamp_ms": 1_789_420_000_007,
            "event_type": event_type,
            "source": "callback",
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "payload": payload,
        }
    )


def test_exact_qmt_remark_token_is_recognized_without_fuzzy_matching():
    assert broker_token_from_remark(TOKEN) == TOKEN
    assert broker_token_from_remark("prefix-" + TOKEN) is None
    assert broker_token_from_remark(TOKEN + "x") is None
    assert broker_token_from_remark("BQ" + "g" * 20) is None
    assert broker_token_from_remark(None) is None


def test_order_calibration_keeps_raw_status_codes_and_token_only():
    event = make_event(
        "order",
        {
            "symbol": "000001.SZ",
            "remark": TOKEN,
            "broker_order_id": "12345",
            "order_ref": "SZ_12345",
            "status_code": 50,
            "submit_status_code": 48,
            "original_quantity": 100,
            "filled_quantity": 0,
        },
    )

    record = order_deal_calibration_record(event)

    assert record.event_type == "order"
    assert record.broker_token == TOKEN
    assert record.broker_order_id == "12345"
    assert record.status_code == 50
    assert record.submit_status_code == 48
    assert record.original_quantity == 100
    assert record.filled_quantity == 0
    assert record.source_event_id == "session-calibration:7"


def test_deal_calibration_records_trade_identity_without_status_mapping():
    event = make_event(
        "deal",
        {
            "symbol": "000001.SZ",
            "remark": TOKEN,
            "broker_order_id": "12345",
            "order_ref": "SZ_12345",
            "trade_id": "T-1",
            "quantity": 100,
        },
    )

    record = order_deal_calibration_record(event)

    assert record.event_type == "deal"
    assert record.broker_token == TOKEN
    assert record.trade_id == "T-1"
    assert record.deal_quantity == 100
    assert record.status_code is None
