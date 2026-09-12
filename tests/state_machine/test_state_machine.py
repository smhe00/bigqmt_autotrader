import pytest

from bigqmt_autotrader.domain import (
    InvalidTransition,
    OrderStatus,
    TransitionDisposition,
    transition,
)


def advance(path):
    current = path[0]
    for target in path[1:]:
        outcome = transition(current, target)
        assert outcome.changed
        current = outcome.current
    return current


def test_happy_path_to_filled():
    assert advance(
        [
            OrderStatus.CREATED,
            OrderStatus.RISK_ACCEPTED,
            OrderStatus.SUBMITTING,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
        ]
    ) is OrderStatus.FILLED


def test_submit_timeout_cannot_jump_directly_out_of_unknown():
    current = advance(
        [
            OrderStatus.CREATED,
            OrderStatus.RISK_ACCEPTED,
            OrderStatus.SUBMITTING,
            OrderStatus.UNKNOWN,
        ]
    )
    with pytest.raises(InvalidTransition):
        transition(current, OrderStatus.ACKNOWLEDGED)
    assert transition(current, OrderStatus.RECONCILING).current is OrderStatus.RECONCILING


def test_duplicate_event_is_idempotent():
    out = transition(OrderStatus.ACKNOWLEDGED, OrderStatus.ACKNOWLEDGED)
    assert not out.changed
    assert out.disposition is TransitionDisposition.DUPLICATE_IGNORED


def test_late_ack_cannot_downgrade_partial_fill():
    out = transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.ACKNOWLEDGED)
    assert out.current is OrderStatus.PARTIALLY_FILLED
    assert out.disposition is TransitionDisposition.STALE_IGNORED


def test_terminal_filled_cannot_be_downgraded():
    out = transition(OrderStatus.FILLED, OrderStatus.ACKNOWLEDGED)
    assert out.current is OrderStatus.FILLED
    assert not out.changed


def test_cancel_fill_race_can_converge():
    assert advance(
        [
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCELLED,
        ]
    ) is OrderStatus.CANCELLED


def test_illegal_transition_fails_closed():
    with pytest.raises(InvalidTransition):
        transition(OrderStatus.CREATED, OrderStatus.FILLED)
