from bigqmt_autotrader.qmt import QmtIngressBuffer, encode_transport_frame
from bigqmt_autotrader.qmt.host import _should_log_event


FP = "sha256:" + "b" * 64


def event(sequence: int, event_type: str, payload: dict):
    return {
        "protocol_version": "0.2",
        "session_id": "session-log",
        "sequence": sequence,
        "timestamp_ms": 1_800_000_000_000 + sequence,
        "event_type": event_type,
        "source": "active_query" if event_type == "snapshot" else "callback",
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "payload": payload,
    }


def test_host_suppresses_routine_duplicate_account_and_position_logs():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    snapshot = ingress.ingest_frame(
        encode_transport_frame(
            event(
                1,
                "snapshot",
                {
                    "account_fingerprint": FP,
                    "account_type": "STOCK",
                    "account": [{"balance": "1000"}],
                    "positions": [],
                    "orders": [],
                    "deals": [],
                    "query_errors": [],
                },
            )
        )
    )
    account = ingress.ingest_frame(
        encode_transport_frame(event(2, "account", {"balance": "1000"}))
    )
    position = ingress.ingest_frame(
        encode_transport_frame(event(3, "position", {"symbol": "000001.SZ", "quantity": 100}))
    )

    assert _should_log_event(snapshot, deduplicated=False, quarantined=False) is True
    assert _should_log_event(account, deduplicated=True, quarantined=False) is False
    assert _should_log_event(position, deduplicated=False, quarantined=False) is False


def test_host_logs_account_change_order_and_resync():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    ingress.ingest_frame(
        encode_transport_frame(
            event(
                1,
                "snapshot",
                {
                    "account_fingerprint": FP,
                    "account_type": "STOCK",
                    "account": [{"balance": "1000"}],
                    "positions": [],
                    "orders": [],
                    "deals": [],
                    "query_errors": [],
                },
            )
        )
    )
    account_change = ingress.ingest_frame(
        encode_transport_frame(event(2, "account", {"balance": "999"}))
    )
    order = ingress.ingest_frame(
        encode_transport_frame(event(3, "order", {"status_code": 50}))
    )
    gap = ingress.ingest_frame(
        encode_transport_frame(event(5, "position", {"symbol": "000001.SZ", "quantity": 100}))
    )

    assert _should_log_event(account_change, deduplicated=False, quarantined=False) is True
    assert _should_log_event(order, deduplicated=False, quarantined=False) is True
    assert _should_log_event(gap, deduplicated=False, quarantined=False) is True
