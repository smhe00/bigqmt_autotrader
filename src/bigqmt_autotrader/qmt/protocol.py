from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Any, Mapping


BRIDGE_PROTOCOL_VERSION = "0.2"
TRANSPORT_VERSION = "1"
MAX_FRAME_BYTES = 1024 * 1024
_ACCOUNT_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_BROKER_TOKEN_RE = re.compile(r"^BQ[0-9a-f]{20}$")
_INSTANCE_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_ALLOWED_EVENT_TYPES = frozenset(
    {
        "snapshot",
        "account",
        "position",
        "order",
        "deal",
        "bridge_ready",
        "bridge_error",
        "command_result",
        "account_capabilities",
    }
)


class QmtProtocolError(ValueError):
    """Malformed or unsupported QMT event envelope."""


class IngressDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    GAP = "GAP"


@dataclass(frozen=True)
class QmtEvent:
    protocol_version: str
    session_id: str
    sequence: int
    timestamp_ms: int
    event_type: str
    source: str
    account_fingerprint: str
    account_type: str | None
    payload: Mapping[str, Any]
    terminal_instance_id: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QmtEvent":
        if not isinstance(value, Mapping):
            raise QmtProtocolError("event must be an object")

        protocol_version = value.get("protocol_version")
        if protocol_version != BRIDGE_PROTOCOL_VERSION:
            raise QmtProtocolError("unsupported bridge protocol version")

        session_id = value.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise QmtProtocolError("session_id must be a non-empty string")

        sequence = value.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
            raise QmtProtocolError("sequence must be a positive integer")

        timestamp_ms = value.get("timestamp_ms")
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms <= 0:
            raise QmtProtocolError("timestamp_ms must be a positive integer")

        event_type = value.get("event_type")
        if event_type not in _ALLOWED_EVENT_TYPES:
            raise QmtProtocolError("unsupported event_type")

        source = value.get("source")
        if not isinstance(source, str) or not source:
            raise QmtProtocolError("source must be a non-empty string")

        account_fingerprint = value.get("account_fingerprint")
        if not isinstance(account_fingerprint, str) or not _ACCOUNT_FINGERPRINT_RE.fullmatch(
            account_fingerprint
        ):
            raise QmtProtocolError("invalid account_fingerprint")

        account_type = value.get("account_type")
        if account_type is not None and not isinstance(account_type, str):
            raise QmtProtocolError("account_type must be a string or null")

        terminal_instance_id = value.get("terminal_instance_id")
        if terminal_instance_id is not None and (
            not isinstance(terminal_instance_id, str)
            or not _INSTANCE_ID_RE.fullmatch(terminal_instance_id)
        ):
            raise QmtProtocolError("invalid terminal_instance_id")

        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise QmtProtocolError("payload must be an object")

        if event_type == "snapshot":
            _validate_snapshot_payload(payload)
        elif event_type == "command_result":
            _validate_command_result_payload(payload)
        elif event_type == "account_capabilities":
            _validate_account_capabilities_payload(payload)

        return cls(
            protocol_version=protocol_version,
            session_id=session_id,
            sequence=sequence,
            timestamp_ms=timestamp_ms,
            event_type=event_type,
            source=source,
            account_fingerprint=account_fingerprint,
            account_type=account_type,
            payload=dict(payload),
            terminal_instance_id=terminal_instance_id,
        )


def _validate_snapshot_payload(payload: Mapping[str, Any]) -> None:
    required_lists = ("account", "positions", "orders", "deals", "query_errors")
    for key in required_lists:
        value = payload.get(key)
        if not isinstance(value, list):
            raise QmtProtocolError(f"snapshot {key} must be a list")
    for key in ("account", "positions", "orders", "deals"):
        if any(not isinstance(row, Mapping) for row in payload[key]):
            raise QmtProtocolError(f"snapshot {key} rows must be objects")


def _validate_account_capabilities_payload(payload: Mapping[str, Any]) -> None:
    selected = payload.get("selected_account_type")
    detected = payload.get("detected_account_types")
    accounts = payload.get("accounts")
    if not isinstance(selected, str) or not selected:
        raise QmtProtocolError("account_capabilities selected_account_type must be non-empty")
    if not isinstance(detected, list) or any(
        not isinstance(item, str) or not item for item in detected
    ):
        raise QmtProtocolError("account_capabilities detected_account_types must be strings")
    if len(set(detected)) != len(detected):
        raise QmtProtocolError("account_capabilities detected_account_types must be unique")
    if not isinstance(accounts, list) or not accounts:
        raise QmtProtocolError("account_capabilities accounts must be a non-empty list")
    seen_types: set[str] = set()
    observed_detected: list[str] = []
    for record in accounts:
        if not isinstance(record, Mapping):
            raise QmtProtocolError("account_capabilities account record must be an object")
        account_type = record.get("account_type")
        fingerprint = record.get("account_fingerprint")
        status = record.get("status")
        if not isinstance(account_type, str) or not account_type or account_type in seen_types:
            raise QmtProtocolError("account_capabilities account_type must be unique")
        seen_types.add(account_type)
        if not isinstance(fingerprint, str) or not _ACCOUNT_FINGERPRINT_RE.fullmatch(fingerprint):
            raise QmtProtocolError("account_capabilities invalid account_fingerprint")
        if status not in {"DETECTED", "DEGRADED", "UNCONFIRMED"}:
            raise QmtProtocolError("account_capabilities invalid status")
        for key in ("account", "positions", "query_errors"):
            rows = record.get(key)
            if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
                raise QmtProtocolError(f"account_capabilities {key} must contain objects")
        if status in {"DETECTED", "DEGRADED"}:
            observed_detected.append(account_type)
    if detected != observed_detected:
        raise QmtProtocolError("account_capabilities detected types do not match records")
    live_submit = payload.get("live_submit")
    live_cancel = payload.get("live_cancel")
    execution_mode = payload.get("execution_mode", "SHADOW")
    if execution_mode == "SHADOW":
        if live_submit is not False or live_cancel is not False:
            raise QmtProtocolError("SHADOW account_capabilities cannot grant live authority")
    elif execution_mode == "SIMULATION_CALIBRATION":
        if (
            live_submit is not True
            or live_cancel is not True
            or payload.get("simulation_only") is not True
        ):
            raise QmtProtocolError("invalid simulation account_capabilities authority")
    else:
        raise QmtProtocolError("account_capabilities execution_mode is unsupported")


def _validate_command_result_payload(payload: Mapping[str, Any]) -> None:
    command_id = payload.get("command_id")
    command_type = payload.get("command_type")
    result_status = payload.get("result_status")
    execution_mode = payload.get("execution_mode")
    live_side_effect = payload.get("live_side_effect")
    if not isinstance(command_id, str) or not command_id:
        raise QmtProtocolError("command_result command_id must be non-empty text")
    if command_type not in {"SUBMIT_LIMIT", "CANCEL_ORDER", "REQUEST_SNAPSHOT"}:
        raise QmtProtocolError("command_result has unsupported command_type")
    shadow_allowed = {
        "SUBMIT_LIMIT": {"SHADOW_ACCEPTED", "REJECTED_EXPIRED", "UNKNOWN_ORPHANED"},
        "CANCEL_ORDER": {"SHADOW_ACCEPTED", "REJECTED_EXPIRED", "UNKNOWN_ORPHANED"},
        "REQUEST_SNAPSHOT": {"SNAPSHOT_EMITTED", "REJECTED_EXPIRED", "UNKNOWN_ORPHANED"},
    }
    simulation_allowed = {
        "SUBMIT_LIMIT": {
            "SIMULATION_SUBMIT_CALL_RETURNED",
            "SIMULATION_MUTATION_UNKNOWN",
            "SIMULATION_ORPHANED_UNKNOWN",
            "REJECTED_SAFETY_GATE",
            "REJECTED_EXPIRED",
        },
        "CANCEL_ORDER": {
            "SIMULATION_CANCEL_SIGNAL_SENT",
            "SIMULATION_CANCEL_NOT_CANCELLABLE",
            "SIMULATION_CANCEL_NOT_SENT",
            "SIMULATION_MUTATION_UNKNOWN",
            "SIMULATION_ORPHANED_UNKNOWN",
            "REJECTED_SAFETY_GATE",
            "REJECTED_EXPIRED",
        },
        "REQUEST_SNAPSHOT": {"SNAPSHOT_EMITTED", "REJECTED_EXPIRED", "UNKNOWN_ORPHANED"},
    }
    if execution_mode == "SHADOW":
        allowed_by_command = shadow_allowed
    elif execution_mode == "SIMULATION_CALIBRATION":
        allowed_by_command = simulation_allowed
    else:
        raise QmtProtocolError("command_result execution_mode is unsupported")
    if result_status not in allowed_by_command.get(command_type, set()):
        raise QmtProtocolError("command_result status is invalid for command_type")
    if not isinstance(live_side_effect, bool):
        raise QmtProtocolError("command_result live_side_effect must be boolean")
    if execution_mode == "SHADOW" and live_side_effect:
        raise QmtProtocolError("SHADOW command_result cannot claim a live side effect")
    simulation_side_effect_statuses = {
        "SIMULATION_SUBMIT_CALL_RETURNED",
        "SIMULATION_CANCEL_SIGNAL_SENT",
        "SIMULATION_CANCEL_NOT_SENT",
        "SIMULATION_MUTATION_UNKNOWN",
        "SIMULATION_ORPHANED_UNKNOWN",
    }
    if execution_mode == "SIMULATION_CALIBRATION" and (
        live_side_effect != (result_status in simulation_side_effect_statuses)
    ):
        raise QmtProtocolError("simulation command_result side-effect flag is inconsistent")

    client_order_id = payload.get("client_order_id")
    broker_token = payload.get("broker_token")
    if command_type == "REQUEST_SNAPSHOT":
        if client_order_id is not None or broker_token is not None:
            raise QmtProtocolError("snapshot command_result cannot carry order identity")
    else:
        if not isinstance(client_order_id, str) or not client_order_id:
            raise QmtProtocolError("order command_result requires client_order_id")
        if not isinstance(broker_token, str) or not _BROKER_TOKEN_RE.fullmatch(broker_token):
            raise QmtProtocolError("order command_result requires a 22-character broker_token")


def encode_transport_frame(event: QmtEvent | Mapping[str, Any]) -> bytes:
    if isinstance(event, QmtEvent):
        event_mapping: Mapping[str, Any] = {
            "protocol_version": event.protocol_version,
            "session_id": event.session_id,
            "sequence": event.sequence,
            "timestamp_ms": event.timestamp_ms,
            "event_type": event.event_type,
            "source": event.source,
            "account_fingerprint": event.account_fingerprint,
            "account_type": event.account_type,
            "terminal_instance_id": event.terminal_instance_id,
            "payload": dict(event.payload),
        }
    else:
        event_mapping = event
        QmtEvent.from_mapping(event_mapping)

    body = {
        "transport_version": TRANSPORT_VERSION,
        "event": event_mapping,
    }
    raw = (json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > MAX_FRAME_BYTES:
        raise QmtProtocolError("transport frame exceeds maximum size")
    return raw


def decode_transport_frame(raw: bytes) -> QmtEvent:
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("raw frame must be bytes")
    if not raw or len(raw) > MAX_FRAME_BYTES:
        raise QmtProtocolError("invalid transport frame size")
    if b"\n" in raw.rstrip(b"\n"):
        raise QmtProtocolError("transport frame must contain exactly one JSON line")
    try:
        body = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QmtProtocolError("invalid JSON transport frame") from exc
    if not isinstance(body, Mapping):
        raise QmtProtocolError("transport frame must be an object")
    if body.get("transport_version") != TRANSPORT_VERSION:
        raise QmtProtocolError("unsupported transport version")
    event = body.get("event")
    if not isinstance(event, Mapping):
        raise QmtProtocolError("transport frame event must be an object")
    return QmtEvent.from_mapping(event)
