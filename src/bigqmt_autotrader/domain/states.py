from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    RISK_REJECTED = "RISK_REJECTED"
    RISK_ACCEPTED = "RISK_ACCEPTED"
    ABORTED = "ABORTED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"
    MANUAL_REVIEW = "MANUAL_REVIEW"


TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.RISK_REJECTED,
        OrderStatus.ABORTED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.MANUAL_REVIEW,
    }
)

AMBIGUOUS_STATUSES = frozenset(
    {
        OrderStatus.SUBMITTING,
        OrderStatus.UNKNOWN,
        OrderStatus.RECONCILING,
        OrderStatus.MANUAL_REVIEW,
    }
)
