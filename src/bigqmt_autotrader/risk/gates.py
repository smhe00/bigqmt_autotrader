from bigqmt_autotrader.domain.states import OrderStatus


_BLOCK_NEW_EXPOSURE = frozenset(
    {
        OrderStatus.SUBMITTING,
        OrderStatus.UNKNOWN,
        OrderStatus.RECONCILING,
        OrderStatus.MANUAL_REVIEW,
    }
)


def blocks_new_exposure(status: OrderStatus) -> bool:
    """Whether ambiguity alone must block potentially duplicative exposure."""
    return status in _BLOCK_NEW_EXPOSURE
