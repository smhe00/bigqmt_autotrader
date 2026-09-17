from __future__ import annotations

import pytest

from bigqmt_autotrader.qmt.protocol import QmtEvent, QmtProtocolError


def event_payload(**payload_overrides):
    payload = {
        "candidates": [
            {"symbol": "00700.SGT", "observed": True, "exchange_id": "SGT"}
        ],
        "attempt": 1,
        "max_attempts": 10,
    }
    payload.update(payload_overrides)
    return {
        "protocol_version": "0.2",
        "terminal_instance_id": "guojin",
        "session_id": "session-1",
        "sequence": 1,
        "timestamp_ms": 1,
        "event_type": "instrument_capabilities",
        "source": "active_query",
        "account_fingerprint": "sha256:" + "a" * 64,
        "account_type": "STOCK",
        "payload": payload,
    }


def test_instrument_capabilities_event_is_accepted():
    parsed = QmtEvent.from_mapping(event_payload())
    assert parsed.event_type == "instrument_capabilities"
    assert parsed.payload["candidates"][0]["exchange_id"] == "SGT"


@pytest.mark.parametrize(
    "overrides",
    [
        {"candidates": []},
        {"attempt": 0},
        {"attempt": True},
        {"attempt": 11, "max_attempts": 10},
    ],
)
def test_instrument_capabilities_event_rejects_invalid_probe_window(overrides):
    with pytest.raises(QmtProtocolError):
        QmtEvent.from_mapping(event_payload(**overrides))
