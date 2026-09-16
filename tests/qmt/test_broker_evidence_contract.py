from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "broker_evidence" / "v1" / "broker_evidence.schema.json"
FP = "sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64


def validator() -> Draft202012Validator:
    value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return Draft202012Validator(value)


def evidence(
    *,
    source_kind: str = "ORDER_CALLBACK",
    evidence_type: str = "ORDER_ACCEPTED",
    requested_status: str = "ACKNOWLEDGED",
    filled_quantity: int = 0,
    broker_order_id: str | None = "10968",
    trade_id: str | None = None,
) -> dict:
    return {
        "evidence_version": "1",
        "source": "qmt-guojin",
        "source_kind": source_kind,
        "source_event_id": "session-1:42",
        "mapper_profile": "qmt-guojin-order-v1",
        "semantic_digest": DIGEST,
        "account_fingerprint": FP,
        "client_order_id": "cid-001",
        "broker_token": "BQ" + "1" * 20,
        "broker_order_id": broker_order_id,
        "order_ref": "ref-001",
        "trade_id": trade_id,
        "evidence_type": evidence_type,
        "requested_status": requested_status,
        "filled_quantity": filled_quantity,
        "observed_at_ms": 1_700_000_000_000,
        "raw_payload_ref": "qmt://guojin/session-1/42",
        "raw_status": {"order_status": 50, "submit_status": 2},
    }


@pytest.mark.parametrize(
    "value",
    [
        evidence(),
        evidence(
            source_kind="DEAL_CALLBACK",
            evidence_type="PARTIAL_FILL",
            requested_status="PARTIALLY_FILLED",
            filled_quantity=50,
            trade_id="trade-1",
        ),
        evidence(
            source_kind="ACTIVE_DEAL_QUERY",
            evidence_type="FULL_FILL",
            requested_status="FILLED",
            filled_quantity=100,
            trade_id=None,
        ),
        evidence(
            source_kind="ACTIVE_ORDER_QUERY",
            evidence_type="ORDER_CANCELLED",
            requested_status="CANCELLED",
            filled_quantity=50,
        ),
        evidence(
            evidence_type="ORDER_REJECTED",
            requested_status="REJECTED",
            filled_quantity=0,
            broker_order_id=None,
        ),
    ],
)
def test_broker_evidence_v1_accepts_legal_samples(value: dict) -> None:
    validator().validate(value)


def test_ack_requires_broker_order_id_and_zero_fill() -> None:
    v = validator()
    missing_broker_id = evidence(broker_order_id=None)
    with pytest.raises(ValidationError):
        v.validate(missing_broker_id)

    nonzero_fill = evidence(filled_quantity=1)
    with pytest.raises(ValidationError):
        v.validate(nonzero_fill)


def test_evidence_type_and_requested_status_are_locked_together() -> None:
    value = evidence()
    value["requested_status"] = "FILLED"
    with pytest.raises(ValidationError):
        validator().validate(value)


def test_deal_sources_have_fill_only_authority() -> None:
    value = evidence(
        source_kind="DEAL_CALLBACK",
        evidence_type="ORDER_CANCELLED",
        requested_status="CANCELLED",
        filled_quantity=0,
        trade_id="trade-1",
    )
    with pytest.raises(ValidationError):
        validator().validate(value)


def test_deal_callback_requires_trade_id() -> None:
    value = evidence(
        source_kind="DEAL_CALLBACK",
        evidence_type="PARTIAL_FILL",
        requested_status="PARTIALLY_FILLED",
        filled_quantity=1,
        trade_id=None,
    )
    with pytest.raises(ValidationError):
        validator().validate(value)


def test_rejected_evidence_cannot_claim_fill() -> None:
    value = evidence(
        evidence_type="ORDER_REJECTED",
        requested_status="REJECTED",
        filled_quantity=1,
        broker_order_id=None,
    )
    with pytest.raises(ValidationError):
        validator().validate(value)


@pytest.mark.parametrize("bad_source", ["COMMAND_RESULT", "UNKNOWN_RAW", "CANCEL_API_RETURN"])
def test_control_or_unknown_sources_cannot_be_broker_evidence(bad_source: str) -> None:
    value = evidence()
    value["source_kind"] = bad_source
    with pytest.raises(ValidationError):
        validator().validate(value)


def test_identity_and_semantic_digest_are_strict() -> None:
    v = validator()
    bad_fp = evidence()
    bad_fp["account_fingerprint"] = "account-raw"
    with pytest.raises(ValidationError):
        v.validate(bad_fp)

    bad_digest = evidence()
    bad_digest["semantic_digest"] = "not-a-digest"
    with pytest.raises(ValidationError):
        v.validate(bad_digest)

    empty_client = evidence()
    empty_client["client_order_id"] = ""
    with pytest.raises(ValidationError):
        v.validate(empty_client)


def test_unknown_fields_fail_closed() -> None:
    value = deepcopy(evidence())
    value["status_code_guess"] = "FILLED"
    with pytest.raises(ValidationError):
        validator().validate(value)
