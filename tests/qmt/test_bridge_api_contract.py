from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from bigqmt_autotrader.qmt.commands import (
    COMMAND_PROTOCOL_VERSION,
    COMMAND_TRANSPORT_VERSION,
    QmtCommandSpool,
)
from bigqmt_autotrader.qmt.protocol import (
    BRIDGE_PROTOCOL_VERSION,
    TRANSPORT_VERSION,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas" / "bridge" / "v1"
FP = "sha256:" + "a" * 64
TOKEN = "BQ" + "1" * 20


def schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    [
        "instance.schema.json",
        "command.schema.json",
        "event.schema.json",
        "command_result.schema.json",
    ],
)
def test_bridge_api_v1_schema_is_valid_draft_2020_12(name: str) -> None:
    Draft202012Validator.check_schema(schema(name))


def shadow_manifest() -> dict:
    return {
        "manifest_version": "1",
        "terminal_instance_id": "guojin",
        "protocol_version": BRIDGE_PROTOCOL_VERSION,
        "transport_version": TRANSPORT_VERSION,
        "bridge_build": "p4-shadow-command-spool-5",
        "session_id": "session-001",
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "created_ms": 1_700_000_000_000,
        "execution_mode": "SHADOW",
        "trading_enabled": False,
        "live_submit": False,
        "live_cancel": False,
    }


def simulation_manifest() -> dict:
    value = shadow_manifest()
    value.update(
        {
            "terminal_instance_id": "guojin_sim",
            "bridge_build": "p5-simulation-calibration-2",
            "execution_mode": "SIMULATION_CALIBRATION",
            "trading_enabled": True,
            "live_submit": True,
            "live_cancel": True,
            "simulation_only": True,
            "authorized_account_fingerprint": FP,
            "max_order_quantity": 100,
            "max_submit_calls_per_session": 2000,
            "max_cancel_calls_per_session": 2000,
        }
    )
    return value


def test_instance_schema_accepts_current_shadow_and_simulation_modes() -> None:
    validator = Draft202012Validator(schema("instance.schema.json"))
    validator.validate(shadow_manifest())
    validator.validate(simulation_manifest())


def test_instance_schema_rejects_live_named_mode_and_shadow_authority() -> None:
    validator = Draft202012Validator(schema("instance.schema.json"))

    live = shadow_manifest()
    live["execution_mode"] = "LIVE"
    with pytest.raises(ValidationError):
        validator.validate(live)

    unsafe_shadow = shadow_manifest()
    unsafe_shadow["live_submit"] = True
    with pytest.raises(ValidationError):
        validator.validate(unsafe_shadow)


def valid_submit_frame(tmp_path: Path) -> dict:
    spool = QmtCommandSpool(tmp_path)
    command = spool.publish_submit(
        account_fingerprint=FP,
        client_order_id="cid-001",
        symbol="000001.SZ",
        side="BUY",
        quantity=100,
        limit_price="10.00",
        created_ms=1_700_000_000_000,
        expires_ms=4_700_000_000_000,
        command_id="command-001",
    )
    return {
        "command_transport_version": COMMAND_TRANSPORT_VERSION,
        "command": {
            "command_protocol_version": COMMAND_PROTOCOL_VERSION,
            "command_id": command.command_id,
            "created_ms": command.created_ms,
            "expires_ms": command.expires_ms,
            "account_fingerprint": command.account_fingerprint,
            "command_type": command.command_type.value,
            "client_order_id": command.client_order_id,
            "broker_token": command.broker_token,
            "payload": dict(command.payload),
        },
    }


def test_command_schema_matches_current_submit_frame(tmp_path: Path) -> None:
    validator = Draft202012Validator(schema("command.schema.json"))
    frame = valid_submit_frame(tmp_path)
    validator.validate(frame)

    bad_token = deepcopy(frame)
    bad_token["command"]["broker_token"] = "BQbad"
    with pytest.raises(ValidationError):
        validator.validate(bad_token)

    wrong_version = deepcopy(frame)
    wrong_version["command"]["command_protocol_version"] = "999"
    with pytest.raises(ValidationError):
        validator.validate(wrong_version)


def test_snapshot_command_must_not_carry_order_identity() -> None:
    validator = Draft202012Validator(schema("command.schema.json"))
    frame = {
        "command_transport_version": COMMAND_TRANSPORT_VERSION,
        "command": {
            "command_protocol_version": COMMAND_PROTOCOL_VERSION,
            "command_id": "snapshot-001",
            "created_ms": 1,
            "expires_ms": 2,
            "account_fingerprint": FP,
            "command_type": "REQUEST_SNAPSHOT",
            "client_order_id": None,
            "broker_token": None,
            "payload": {},
        },
    }
    validator.validate(frame)
    frame["command"]["client_order_id"] = "not-allowed"
    with pytest.raises(ValidationError):
        validator.validate(frame)


def shadow_command_result() -> dict:
    return {
        "command_id": "command-001",
        "command_type": "SUBMIT_LIMIT",
        "result_status": "SHADOW_ACCEPTED",
        "execution_mode": "SHADOW",
        "live_side_effect": False,
        "client_order_id": "cid-001",
        "broker_token": TOKEN,
    }


def test_command_result_schema_enforces_control_plane_semantics() -> None:
    validator = Draft202012Validator(schema("command_result.schema.json"))
    payload = shadow_command_result()
    validator.validate(payload)

    claims_side_effect = deepcopy(payload)
    claims_side_effect["live_side_effect"] = True
    with pytest.raises(ValidationError):
        validator.validate(claims_side_effect)

    invalid_status_pair = deepcopy(payload)
    invalid_status_pair["result_status"] = "SIMULATION_SUBMIT_CALL_RETURNED"
    with pytest.raises(ValidationError):
        validator.validate(invalid_status_pair)


def test_event_schema_embeds_command_result_contract() -> None:
    validator = Draft202012Validator(schema("event.schema.json"))
    frame = {
        "transport_version": TRANSPORT_VERSION,
        "event": {
            "protocol_version": BRIDGE_PROTOCOL_VERSION,
            "session_id": "session-001",
            "sequence": 1,
            "timestamp_ms": 1_700_000_000_000,
            "event_type": "command_result",
            "source": "bridge-contract-test",
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "terminal_instance_id": "guojin",
            "payload": shadow_command_result(),
        },
    }
    validator.validate(frame)

    unsafe = deepcopy(frame)
    unsafe["event"]["payload"]["live_side_effect"] = True
    with pytest.raises(ValidationError):
        validator.validate(unsafe)
