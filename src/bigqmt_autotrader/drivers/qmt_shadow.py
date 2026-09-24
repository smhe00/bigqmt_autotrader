from __future__ import annotations

from collections.abc import Callable

from bigqmt_autotrader.domain import OrderIntent
from bigqmt_autotrader.qmt.commands import QmtCommandSpool, broker_token_for
from bigqmt_autotrader.ports import CancelOutcomeUnknown, SubmitOutcomeUnknown


class QmtShadowDriver:
    """OMS-facing asynchronous QMT driver for P4 shadow calibration.

    A successful durable command publication is intentionally *not* broker
    acknowledgement. The driver therefore raises SubmitOutcomeUnknown /
    CancelOutcomeUnknown after dispatch so the existing OMS transitions to
    UNKNOWN and waits for calibrated broker callback/query evidence rather than
    fabricating ACKNOWLEDGED/CANCELLED state.
    """

    def __init__(
        self,
        command_spool: QmtCommandSpool,
        *,
        cancel_broker_id_resolver: Callable[[str, str], str | None] | None = None,
    ) -> None:
        self.command_spool = command_spool
        self.cancel_broker_id_resolver = cancel_broker_id_resolver

    def submit_limit_order(self, intent: OrderIntent):
        token = broker_token_for(intent.account_fingerprint, intent.client_order_id)
        command_id = "submit-" + token
        self.command_spool.publish_submit(
            account_fingerprint=intent.account_fingerprint,
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=intent.side.value,
            quantity=intent.quantity,
            limit_price=str(intent.limit_price),
            created_ms=int(intent.created_at.timestamp() * 1000),
            expires_ms=int(intent.expires_at.timestamp() * 1000),
            command_id=command_id,
        )
        raise SubmitOutcomeUnknown(
            "QMT shadow command durably dispatched; broker outcome intentionally unresolved"
        )

    def cancel_order(self, account_fingerprint: str, client_order_id: str):
        if self.cancel_broker_id_resolver is None:
            raise CancelOutcomeUnknown(
                "QMT shadow cancel requires a durable broker_order_id resolver"
            )
        broker_order_id = self.cancel_broker_id_resolver(account_fingerprint, client_order_id)
        if not broker_order_id:
            raise CancelOutcomeUnknown(
                "QMT shadow cancel has no durable broker_order_id; cancel not dispatched"
            )
        token = broker_token_for(account_fingerprint, client_order_id)
        self.command_spool.publish_cancel(
            account_fingerprint=account_fingerprint,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            expires_ms=2**63 - 1,
            command_id="cancel-" + token,
        )
        raise CancelOutcomeUnknown(
            "QMT shadow cancel durably dispatched; broker outcome intentionally unresolved"
        )

    def query_by_client_order_id(self, account_fingerprint: str, client_order_id: str):
        # SHADOW_ACCEPTED is transport evidence, not broker order evidence.
        # Returning None prevents accidental promotion to ACKNOWLEDGED.
        return None
