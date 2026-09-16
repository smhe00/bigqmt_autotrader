from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import json
from pathlib import Path


STATUSES = (
    "UNKNOWN",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "MANUAL_REVIEW",
)
TARGETS = (
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
)
TERMINAL = {"FILLED", "CANCELLED", "REJECTED"}
BROKER_SOURCES = {
    "ORDER_CALLBACK",
    "DEAL_CALLBACK",
    "ACTIVE_ORDER_QUERY",
    "ACTIVE_DEAL_QUERY",
}
SOURCES = (
    "COMMAND_RESULT",
    "ORDER_CALLBACK",
    "DEAL_CALLBACK",
    "ACTIVE_ORDER_QUERY",
    "ACTIVE_DEAL_QUERY",
    "UNKNOWN_RAW",
)
ORDER_QTY = 2

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "broker_evidence" / "v1" / "broker_evidence.schema.json"


@dataclass(frozen=True)
class State:
    status: str
    filled: int


@dataclass(frozen=True)
class Event:
    source: str
    target: str
    filled: int
    identity_match: bool
    raw_known: bool
    exact_duplicate: bool = False
    semantic_conflict: bool = False


def rank(status: str) -> int:
    if status == "UNKNOWN":
        return 0
    if status == "ACKNOWLEDGED":
        return 1
    if status == "PARTIALLY_FILLED":
        return 2
    if status in TERMINAL:
        return 3
    if status == "MANUAL_REVIEW":
        return 4
    raise AssertionError(status)


def source_allows(source: str, target: str) -> bool:
    if source in {"ORDER_CALLBACK", "ACTIVE_ORDER_QUERY"}:
        return target in TARGETS
    if source in {"DEAL_CALLBACK", "ACTIVE_DEAL_QUERY"}:
        return target in {"PARTIALLY_FILLED", "FILLED"}
    return False


def quantity_valid(target: str, qty: int) -> bool:
    if target == "ACKNOWLEDGED":
        return qty == 0
    if target == "PARTIALLY_FILLED":
        return qty == 1
    if target == "FILLED":
        return qty == ORDER_QTY
    if target == "CANCELLED":
        return 0 <= qty < ORDER_QTY
    if target == "REJECTED":
        return qty == 0
    return False


def is_candidate(event: Event) -> bool:
    return (
        event.source in BROKER_SOURCES
        and event.identity_match
        and event.raw_known
        and source_allows(event.source, event.target)
        and quantity_valid(event.target, event.filled)
    )


def lifecycle_conflict(state: State, event: Event) -> bool:
    return (
        (state.status in TERMINAL and event.target in TERMINAL and event.target != state.status)
        or (state.status in {"CANCELLED", "REJECTED"} and event.filled > state.filled)
        or (event.target == "REJECTED" and state.filled > 0)
    )


def apply(state: State, event: Event) -> State:
    if event.exact_duplicate:
        return state

    if event.semantic_conflict:
        return State("MANUAL_REVIEW", state.filled)

    if not is_candidate(event):
        return state

    next_filled = max(state.filled, event.filled)

    if state.status == "MANUAL_REVIEW":
        return State("MANUAL_REVIEW", next_filled)

    if lifecycle_conflict(state, event):
        return State("MANUAL_REVIEW", next_filled)

    if state.status in TERMINAL:
        return State(state.status, next_filled)

    if event.target == "ACKNOWLEDGED":
        next_status = "ACKNOWLEDGED" if state.status == "UNKNOWN" else state.status
    elif event.target == "PARTIALLY_FILLED":
        next_status = "PARTIALLY_FILLED"
    else:
        next_status = event.target

    return State(next_status, next_filled)


VALID_STATES = (
    State("UNKNOWN", 0),
    State("ACKNOWLEDGED", 0),
    State("PARTIALLY_FILLED", 1),
    State("FILLED", 2),
    State("CANCELLED", 0),
    State("CANCELLED", 1),
    State("REJECTED", 0),
    State("MANUAL_REVIEW", 0),
    State("MANUAL_REVIEW", 1),
    State("MANUAL_REVIEW", 2),
)


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    props = schema["properties"]
    assert set(props["source_kind"]["enum"]) == BROKER_SOURCES
    assert set(props["requested_status"]["enum"]) == set(TARGETS)
    assert set(props["evidence_type"]["enum"]) == {
        "ORDER_ACCEPTED",
        "PARTIAL_FILL",
        "FULL_FILL",
        "ORDER_CANCELLED",
        "ORDER_REJECTED",
    }
    assert props["evidence_version"]["const"] == "1"

    encoded_schema = json.dumps(schema, sort_keys=True)
    for forbidden in ("COMMAND_RESULT", "UNKNOWN_RAW", "CANCEL_API_RETURN", "SHADOW_ACCEPTED"):
        assert forbidden not in encoded_schema

    cases = 0

    for state, source, target, qty, identity_match, raw_known, duplicate in product(
        VALID_STATES,
        SOURCES,
        TARGETS,
        range(ORDER_QTY + 1),
        (False, True),
        (False, True),
        (False, True),
    ):
        event = Event(
            source=source,
            target=target,
            filled=qty,
            identity_match=identity_match,
            raw_known=raw_known,
            exact_duplicate=duplicate,
        )
        nxt = apply(state, event)
        cases += 1

        assert nxt.status in STATUSES
        assert 0 <= nxt.filled <= ORDER_QTY
        assert nxt.filled >= state.filled
        assert rank(nxt.status) >= rank(state.status)

        if duplicate:
            assert nxt == state
            continue

        if source == "COMMAND_RESULT":
            assert nxt == state, "command_result promoted OMS lifecycle"
        if source == "UNKNOWN_RAW" or not raw_known:
            assert nxt == state, "unknown raw status advanced OMS"
        if not identity_match:
            assert nxt == state, "identity mismatch mutated OMS"
        if source in {"DEAL_CALLBACK", "ACTIVE_DEAL_QUERY"} and target in {
            "ACKNOWLEDGED",
            "CANCELLED",
            "REJECTED",
        }:
            assert nxt == state, "DEAL evidence exceeded fill-only authority"

        if state.status == "PARTIALLY_FILLED" and target == "ACKNOWLEDGED":
            assert nxt.status != "ACKNOWLEDGED"
        if state.status == "FILLED" and target not in TERMINAL:
            assert nxt.status == "FILLED"
        if state.status in TERMINAL and target in TERMINAL and target != state.status:
            if is_candidate(event):
                assert nxt.status == "MANUAL_REVIEW"
        if state.status in {"CANCELLED", "REJECTED"} and qty > state.filled:
            if is_candidate(event):
                assert nxt.status == "MANUAL_REVIEW"
        if nxt.status == "REJECTED":
            assert nxt.filled == 0
        if nxt.status == "CANCELLED":
            assert nxt.filled < ORDER_QTY

    base = State("PARTIALLY_FILLED", 1)
    duplicate = Event(
        source="DEAL_CALLBACK",
        target="PARTIALLY_FILLED",
        filled=1,
        identity_match=True,
        raw_known=True,
        exact_duplicate=True,
    )
    conflict = Event(
        source="DEAL_CALLBACK",
        target="PARTIALLY_FILLED",
        filled=1,
        identity_match=True,
        raw_known=True,
        semantic_conflict=True,
    )
    assert apply(base, duplicate) == base
    assert apply(base, conflict).status == "MANUAL_REVIEW"

    cancel_signal = Event(
        source="COMMAND_RESULT",
        target="CANCELLED",
        filled=0,
        identity_match=True,
        raw_known=True,
    )
    assert apply(State("ACKNOWLEDGED", 0), cancel_signal) == State("ACKNOWLEDGED", 0)

    cancelled = apply(
        State("PARTIALLY_FILLED", 1),
        Event(
            source="ACTIVE_ORDER_QUERY",
            target="CANCELLED",
            filled=1,
            identity_match=True,
            raw_known=True,
        ),
    )
    assert cancelled == State("CANCELLED", 1)

    conflict_terminal = apply(
        State("FILLED", 2),
        Event(
            source="ACTIVE_ORDER_QUERY",
            target="CANCELLED",
            filled=1,
            identity_match=True,
            raw_known=True,
        ),
    )
    assert conflict_terminal.status == "MANUAL_REVIEW"

    print(f"Broker Evidence Contract v1 finite matrix: PASS ({cases} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
