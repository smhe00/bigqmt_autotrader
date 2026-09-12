from bigqmt_autotrader.domain import OrderStatus
from bigqmt_autotrader.risk import blocks_new_exposure


def test_unknown_blocks_new_exposure():
    assert blocks_new_exposure(OrderStatus.UNKNOWN)
    assert blocks_new_exposure(OrderStatus.RECONCILING)
    assert blocks_new_exposure(OrderStatus.SUBMITTING)


def test_resolved_terminal_order_does_not_block_on_ambiguity_rule_alone():
    assert not blocks_new_exposure(OrderStatus.FILLED)
    assert not blocks_new_exposure(OrderStatus.CANCELLED)
