import pytest

from bigqmt_autotrader.qmt import (
    QmtHostIngestion,
    QmtIngressBuffer,
    QmtProtocolError,
    encode_transport_frame,
)
from bigqmt_autotrader.qmt.host import _event_summary, _should_log_event


FP = "sha256:" + "a" * 64
HGT_FP = "sha256:" + "b" * 64


def capability_event(payload: dict) -> dict:
    return {
        "protocol_version": "0.2",
        "session_id": "session-capability",
        "sequence": 1,
        "timestamp_ms": 1_800_000_000_001,
        "event_type": "account_capabilities",
        "source": "active_query",
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "payload": payload,
    }


def payload() -> dict:
    return {
        "selected_account_type": "STOCK",
        "detected_account_types": ["STOCK", "HUGANGTONG"],
        "accounts": [
            {
                "account_type": "STOCK",
                "account_fingerprint": FP,
                "status": "DETECTED",
                "account": [{"status": "OK"}],
                "positions": [{"symbol": "510050.SH", "quantity": 100}],
                "query_errors": [],
            },
            {
                "account_type": "HUGANGTONG",
                "account_fingerprint": HGT_FP,
                "status": "DETECTED",
                "account": [{"status": "OK"}],
                "positions": [{"symbol": "00700.HGT", "quantity": 300}],
                "query_errors": [],
            },
        ],
        "live_submit": False,
        "live_cancel": False,
    }


def test_host_retains_linked_account_views_without_changing_primary_identity():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    host = QmtHostIngestion()
    ingress_result = ingress.ingest_frame(encode_transport_frame(capability_event(payload())))
    result = host.handle(ingress_result)

    assert result.quarantined is False
    assert host.read_model.view is None
    assert [row["account_type"] for row in host.read_model.linked_accounts] == [
        "STOCK",
        "HUGANGTONG",
    ]
    assert host.read_model.linked_accounts[1]["positions"][0]["symbol"] == "00700.HGT"

    summary = _event_summary(ingress_result, host)
    assert summary["detected_account_types"] == ["STOCK", "HUGANGTONG"]
    assert summary["detected_account_count"] == 2
    assert "00700.HGT" not in repr(summary)
    assert "quantity" not in repr(summary)
    assert _should_log_event(ingress_result, deduplicated=False, quarantined=False) is True


def test_capability_event_cannot_grant_live_authority():
    value = payload()
    value["live_submit"] = True
    with pytest.raises(QmtProtocolError, match="cannot grant live"):
        encode_transport_frame(capability_event(value))


def test_capability_event_allows_explicit_simulation_only_authority():
    value = payload()
    value.update(
        {
            "execution_mode": "SIMULATION_CALIBRATION",
            "simulation_only": True,
            "live_submit": True,
            "live_cancel": True,
        }
    )

    assert encode_transport_frame(capability_event(value))


def test_capability_event_allows_explicit_live_canary_authority():
    value = payload()
    value.update(
        {
            "execution_mode": "LIVE_CANARY",
            "simulation_only": False,
            "live_submit": True,
            "live_cancel": True,
        }
    )

    assert encode_transport_frame(capability_event(value))


def test_capability_event_rejects_detected_list_that_disagrees_with_records():
    value = payload()
    value["detected_account_types"] = ["STOCK"]
    with pytest.raises(QmtProtocolError, match="do not match"):
        encode_transport_frame(capability_event(value))
