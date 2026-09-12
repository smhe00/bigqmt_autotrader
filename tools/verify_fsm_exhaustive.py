#!/usr/bin/env python3
"""Exhaustive implementation/spec conformance check for the finite order FSM.

This is intentionally independent of the implementation's private _ALLOWED/_STALE
objects. It enumerates every current/requested pair and compares the observed
Python behavior against the frozen formal contract mirrored by formal/OrderFSM.tla.
"""

from collections import deque

from bigqmt_autotrader.domain import (
    InvalidTransition,
    OrderStatus,
    TransitionDisposition,
    transition,
)
from bigqmt_autotrader.domain.states import TERMINAL_STATUSES

S = OrderStatus

ALLOWED = {
    (S.CREATED, S.RISK_REJECTED),
    (S.CREATED, S.RISK_ACCEPTED),
    (S.CREATED, S.ABORTED),
    (S.RISK_ACCEPTED, S.SUBMITTING),
    (S.RISK_ACCEPTED, S.ABORTED),
    (S.SUBMITTING, S.ACKNOWLEDGED),
    (S.SUBMITTING, S.REJECTED),
    (S.SUBMITTING, S.UNKNOWN),
    (S.ACKNOWLEDGED, S.PARTIALLY_FILLED),
    (S.ACKNOWLEDGED, S.FILLED),
    (S.ACKNOWLEDGED, S.CANCEL_PENDING),
    (S.PARTIALLY_FILLED, S.FILLED),
    (S.PARTIALLY_FILLED, S.CANCEL_PENDING),
    (S.PARTIALLY_FILLED, S.CANCELLED),
    (S.CANCEL_PENDING, S.CANCELLED),
    (S.CANCEL_PENDING, S.PARTIALLY_FILLED),
    (S.CANCEL_PENDING, S.FILLED),
    (S.CANCEL_PENDING, S.UNKNOWN),
    (S.UNKNOWN, S.RECONCILING),
    (S.RECONCILING, S.ACKNOWLEDGED),
    (S.RECONCILING, S.PARTIALLY_FILLED),
    (S.RECONCILING, S.FILLED),
    (S.RECONCILING, S.REJECTED),
    (S.RECONCILING, S.CANCELLED),
    (S.RECONCILING, S.MANUAL_REVIEW),
}

EXPLICIT_STALE = {
    (S.RISK_ACCEPTED, S.CREATED),
    (S.SUBMITTING, S.CREATED),
    (S.SUBMITTING, S.RISK_ACCEPTED),
    (S.ACKNOWLEDGED, S.CREATED),
    (S.ACKNOWLEDGED, S.RISK_ACCEPTED),
    (S.ACKNOWLEDGED, S.SUBMITTING),
    (S.PARTIALLY_FILLED, S.CREATED),
    (S.PARTIALLY_FILLED, S.RISK_ACCEPTED),
    (S.PARTIALLY_FILLED, S.SUBMITTING),
    (S.PARTIALLY_FILLED, S.ACKNOWLEDGED),
    (S.CANCEL_PENDING, S.CREATED),
    (S.CANCEL_PENDING, S.RISK_ACCEPTED),
    (S.CANCEL_PENDING, S.SUBMITTING),
    (S.CANCEL_PENDING, S.ACKNOWLEDGED),
}


def classify(current: S, requested: S) -> str:
    tags = set()
    if current == requested:
        tags.add("duplicate")
    if (current, requested) in ALLOWED:
        tags.add("applied")
    if (current in TERMINAL_STATUSES and current != requested) or (
        current,
        requested,
    ) in EXPLICIT_STALE:
        tags.add("stale")
    if not tags:
        tags.add("illegal")
    if len(tags) != 1:
        raise AssertionError(
            f"formal classification is not exclusive: {current.value}->{requested.value}: {tags}"
        )
    return next(iter(tags))


def verify_pair(current: S, requested: S) -> None:
    expected = classify(current, requested)
    try:
        outcome = transition(current, requested)
    except InvalidTransition:
        if expected != "illegal":
            raise AssertionError(
                f"implementation rejected formal {expected} pair: {current.value}->{requested.value}"
            )
        return

    if expected == "illegal":
        raise AssertionError(
            f"implementation accepted formally illegal pair: {current.value}->{requested.value}"
        )

    if expected == "applied":
        assert outcome.changed
        assert outcome.current is requested
        assert outcome.disposition is TransitionDisposition.APPLIED
    elif expected == "duplicate":
        assert not outcome.changed
        assert outcome.current is current
        assert outcome.disposition is TransitionDisposition.DUPLICATE_IGNORED
    elif expected == "stale":
        assert not outcome.changed
        assert outcome.current is current
        assert outcome.disposition is TransitionDisposition.STALE_IGNORED
    else:  # pragma: no cover - classify is exhaustive
        raise AssertionError(expected)


def reachable_from(start: S) -> set[S]:
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for src, dst in ALLOWED:
            if src is current and dst not in seen:
                seen.add(dst)
                queue.append(dst)
    return seen


def transitive_reachable(start: S) -> set[S]:
    return reachable_from(start) - {start}


def main() -> None:
    statuses = tuple(S)
    expected_pairs = len(statuses) * len(statuses)
    checked = 0
    counts = {"applied": 0, "duplicate": 0, "stale": 0, "illegal": 0}

    assert ALLOWED.isdisjoint(EXPLICIT_STALE)

    for current in statuses:
        for requested in statuses:
            category = classify(current, requested)
            counts[category] += 1
            verify_pair(current, requested)
            checked += 1

    assert checked == expected_pairs == 196

    reached = reachable_from(S.CREATED)
    missing = set(statuses) - reached
    assert not missing, f"unreachable states from CREATED: {[x.value for x in sorted(missing, key=lambda x: x.value)]}"

    for terminal in TERMINAL_STATUSES:
        assert not any(src is terminal for src, _ in ALLOWED), (
            f"terminal state has applied exit: {terminal.value}"
        )

    unknown_targets = {dst for src, dst in ALLOWED if src is S.UNKNOWN}
    assert unknown_targets == {S.RECONCILING}

    abort_sources = {src for src, dst in ALLOWED if dst is S.ABORTED}
    assert abort_sources == {S.CREATED, S.RISK_ACCEPTED}

    pre_submit = {S.CREATED, S.RISK_ACCEPTED, S.SUBMITTING}
    for start in (S.UNKNOWN, S.RECONCILING):
        leaked = transitive_reachable(start) & pre_submit
        assert not leaked, (
            f"ambiguity path can return to pre-submit states from {start.value}: "
            f"{[x.value for x in leaked]}"
        )
        assert S.ABORTED not in transitive_reachable(start), (
            f"post-submit ambiguity can incorrectly reach ABORTED from {start.value}"
        )

    print(
        "FSM formal conformance PASS: "
        f"{checked} state/request pairs; "
        f"{len(ALLOWED)} applied edges; "
        f"reachable={len(reached)}/{len(statuses)}; "
        f"classification={counts}"
    )


if __name__ == "__main__":
    main()
