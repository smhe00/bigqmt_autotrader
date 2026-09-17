from __future__ import annotations

import json
from pathlib import Path

from bigqmt_autotrader.qmt.commands import (
    COMMAND_PROTOCOL_VERSION,
    COMMAND_TRANSPORT_VERSION,
    QmtCommandType,
)
from bigqmt_autotrader.qmt.instances import INSTANCE_MANIFEST_VERSION
from bigqmt_autotrader.qmt.protocol import (
    BRIDGE_PROTOCOL_VERSION,
    TRANSPORT_VERSION,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" / "bridge" / "v1"


def load(name: str) -> dict:
    value = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must contain a JSON object")
    return value


def command_type_enum(command_schema: dict) -> set[str]:
    return set(
        command_schema["properties"]["command"]["properties"]["command_type"]["enum"]
    )


def event_type_enum(event_schema: dict) -> set[str]:
    return set(
        event_schema["properties"]["event"]["properties"]["event_type"]["enum"]
    )


def main() -> int:
    instance = load("instance.schema.json")
    command = load("command.schema.json")
    event = load("event.schema.json")
    command_result = load("command_result.schema.json")

    assert instance["properties"]["manifest_version"]["const"] == INSTANCE_MANIFEST_VERSION
    assert instance["properties"]["protocol_version"]["const"] == BRIDGE_PROTOCOL_VERSION
    assert instance["properties"]["transport_version"]["const"] == TRANSPORT_VERSION

    command_inner = command["properties"]["command"]
    assert command["properties"]["command_transport_version"]["const"] == COMMAND_TRANSPORT_VERSION
    assert command_inner["properties"]["command_protocol_version"]["const"] == COMMAND_PROTOCOL_VERSION
    assert command_type_enum(command) == {item.value for item in QmtCommandType}

    assert event["properties"]["transport_version"]["const"] == TRANSPORT_VERSION
    assert (
        event["properties"]["event"]["properties"]["protocol_version"]["const"]
        == BRIDGE_PROTOCOL_VERSION
    )
    assert event_type_enum(event) == {
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

    for schema in (instance, command_result):
        encoded = json.dumps(schema, sort_keys=True)
        assert '"LIVE"' not in encoded
        assert '"LIVE_ARMED"' not in encoded

    command_result_modes = set(
        command_result["properties"]["execution_mode"]["enum"]
    )
    assert command_result_modes == {
        "SHADOW",
        "SIMULATION_CALIBRATION",
        "LIVE_CANARY",
    }

    print("Bridge API v1 schema/implementation constants: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
