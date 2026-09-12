from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .states import OrderStatus, TERMINAL_STATUSES


class InvalidTransition(ValueError):
    pass


class TransitionDisposition(str, Enum):
    APPLIED = "APPLIED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    STALE_IGNORED = "STALE_IGNORED"


@dataclass(frozen=True)
class TransitionOutcome:
    previous: OrderStatus
    current: OrderStatus
    requested: OrderStatus
    changed: bool
    disposition: TransitionDisposition


_ALLOWED = {
    OrderStatus.CREATED: {
        OrderStatus.RISK_REJECTED,
        OrderStatus.RISK_ACCEPTED,
        OrderStatus.ABORTED,
    },
    OrderStatus.RISK_ACCEPTED: {
        OrderStatus.SUBMITTING,
        OrderStatus.ABORTED,
    },
    OrderStatus.SUBMITTING: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.REJECTED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.ACKNOWLEDGED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCEL_PENDING,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.FILLED,
        OrderStatus.CANCEL_PENDING,
        # Required to converge when cancel/fill callbacks race and the partial-fill
        # callback is observed after CANCEL_PENDING.
        OrderStatus.CANCELLED,
    },
    OrderStatus.CANCEL_PENDING: {
        OrderStatus.CANCELLED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.UNKNOWN: {OrderStatus.RECONCILING},
    OrderStatus.RECONCILING: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
        OrderStatus.MANUAL_REVIEW,
    },
}

# Explicit broker states that are older than the current state. They may be
# recorded as raw evidence by P1, but they must never downgrade the aggregate.
_STALE = {
    OrderStatus.RISK_ACCEPTED: {OrderStatus.CREATED},
    OrderStatus.SUBMITTING: {OrderStatus.CREATED, OrderStatus.RISK_ACCEPTED},
    OrderStatus.ACKNOWLEDGED: {
        OrderStatus.CREATED,
        OrderStatus.RISK_ACCEPTED,
        OrderStatus.SUBMITTING,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.CREATED,
        OrderStatus.RISK_ACCEPTED,
        OrderStatus.SUBMITTING,
        OrderStatus.ACKNOWLEDGED,
    },
    OrderStatus.CANCEL_PENDING: {
        OrderStatus.CREATED,
        OrderStatus.RISK_ACCEPTED,
        OrderStatus.SUBMITTING,
        OrderStatus.ACKNOWLEDGED,
    },
}


def transition(current: OrderStatus, requested: OrderStatus) -> TransitionOutcome:
    """Apply one deterministic monotonic state transition.

    Unknown outcomes are never inferred away. UNKNOWN can only move to
    RECONCILING; reconciliation evidence then selects an explicit next state.
    Pre-side-effect restart recovery may terminate CREATED/RISK_ACCEPTED as
    ABORTED, but ABORTED itself is absorbing and can never lead to submission.
    """
    if current == requested:
        return TransitionOutcome(
            previous=current,
            current=current,
            requested=requested,
            changed=False,
            disposition=TransitionDisposition.DUPLICATE_IGNORED,
        )

    if current in TERMINAL_STATUSES:
        return TransitionOutcome(
            previous=current,
            current=current,
            requested=requested,
            changed=False,
            disposition=TransitionDisposition.STALE_IGNORED,
        )

    if requested in _ALLOWED.get(current, set()):
        return TransitionOutcome(
            previous=current,
            current=requested,
            requested=requested,
            changed=True,
            disposition=TransitionDisposition.APPLIED,
        )

    if requested in _STALE.get(current, set()):
        return TransitionOutcome(
            previous=current,
            current=current,
            requested=requested,
            changed=False,
            disposition=TransitionDisposition.STALE_IGNORED,
        )

    raise InvalidTransition(f"illegal order transition: {current.value} -> {requested.value}")
