from __future__ import annotations

from datetime import datetime, timezone

from bigqmt_autotrader.domain import OrderStatus, TransitionDisposition
from bigqmt_autotrader.oms.db import transaction
from bigqmt_autotrader.oms.repository import OmsRepository


class QmtDurableIdentityConflict(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_qmt_durable_submit(
    repository: OmsRepository,
    *,
    command_id: str,
    account_fingerprint: str,
    qmt_session_id: str,
    client_order_id: str,
    broker_token: str,
    symbol: str,
    side: str,
    quantity: int,
    limit_price: str,
    command_state: str,
    command_digest: str,
    created_ms: int,
    expires_ms: int,
    allow_existing_order_from_dispatch: bool = False,
) -> bool:
    """Join an already-issued QMT submit to Core without treating it as broker ACK."""
    identity = (
        command_id, account_fingerprint, qmt_session_id, client_order_id,
        broker_token, symbol, side, quantity, limit_price, command_state,
        command_digest, created_ms, expires_ms,
    )
    conn = repository.conn
    with transaction(conn):
        repository._guard_write_in_tx()
        row = conn.execute(
            """
            SELECT * FROM qmt_durable_command_identities
            WHERE command_id=? OR (account_fingerprint=? AND client_order_id=?)
               OR (account_fingerprint=? AND broker_token=?)
            """,
            (command_id, account_fingerprint, client_order_id,
             account_fingerprint, broker_token),
        ).fetchone()
        if row is not None:
            stored = tuple(row[key] for key in (
                "command_id", "account_fingerprint", "qmt_session_id",
                "client_order_id", "broker_token", "symbol", "side",
                "quantity", "limit_price", "command_state", "command_digest",
                "created_ms", "expires_ms",
            ))
            if (
                stored[:9] == identity[:9]
                and stored[10:] == identity[10:]
                and stored[9] == "unknown"
                and command_state == "processed"
            ):
                conn.execute(
                    "UPDATE qmt_durable_command_identities "
                    "SET command_state='processed' WHERE command_id=?",
                    (command_id,),
                )
                return False
            if stored != identity:
                raise QmtDurableIdentityConflict("conflicting durable QMT command identity")
            return False

        existing_order = conn.execute(
            """SELECT 1 FROM order_intents
               WHERE account_fingerprint=? AND client_order_id=?""",
            (account_fingerprint, client_order_id),
        ).fetchone()
        if existing_order is not None:
            if not allow_existing_order_from_dispatch:
                raise QmtDurableIdentityConflict(
                    "OMS order exists without matching durable QMT identity"
                )
            conn.execute(
                """INSERT INTO qmt_durable_command_identities(
                       command_id, account_fingerprint, qmt_session_id, client_order_id,
                       broker_token, symbol, side, quantity, limit_price, command_state,
                       command_digest, created_ms, expires_ms, imported_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                identity + (_utc_now(),),
            )
            current = repository._get_status_in_tx(account_fingerprint, client_order_id)
            repository._insert_event(
                account_fingerprint,
                client_order_id,
                event_type="QMT_DURABLE_SUBMIT_LINKED_TO_OMS_DISPATCH",
                from_status=current,
                to_status=current,
                disposition=TransitionDisposition.APPLIED,
                evidence={
                    "command_id": command_id,
                    "qmt_session_id": qmt_session_id,
                    "command_state": command_state,
                    "broker_token": broker_token,
                },
            )
            return True

        created_at = datetime.fromtimestamp(created_ms / 1000.0, tz=timezone.utc).isoformat()
        expires_at = datetime.fromtimestamp(expires_ms / 1000.0, tz=timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO order_intents(
                   account_fingerprint, client_order_id, strategy_id, strategy_version,
                   symbol, side, order_type, quantity, limit_price, created_at,
                   expires_at, signal_id, reason_code
               ) VALUES(?, ?, 'qmt-guojin-sim-import', '1', ?, ?, 'LIMIT', ?, ?, ?, ?, ?,
                        'DURABLE_QMT_COMMAND_RECOVERY')""",
            (account_fingerprint, client_order_id, symbol, side, quantity,
             limit_price, created_at, expires_at, command_id),
        )
        conn.execute(
            """INSERT INTO broker_orders(
                   account_fingerprint, client_order_id, status, broker_order_id,
                   filled_quantity, submit_call_started, cancel_call_started,
                   cancel_outcome_resolved, updated_at
               ) VALUES(?, ?, ?, NULL, 0, 1, 0, 0, ?)""",
            (account_fingerprint, client_order_id, OrderStatus.RECONCILING.value, _utc_now()),
        )
        conn.execute(
            """INSERT INTO qmt_durable_command_identities(
                   command_id, account_fingerprint, qmt_session_id, client_order_id,
                   broker_token, symbol, side, quantity, limit_price, command_state,
                   command_digest, created_ms, expires_ms, imported_at
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            identity + (_utc_now(),),
        )
        repository._insert_event(
            account_fingerprint,
            client_order_id,
            event_type="QMT_DURABLE_SUBMIT_REGISTERED",
            from_status=None,
            to_status=OrderStatus.RECONCILING,
            disposition=TransitionDisposition.APPLIED,
            evidence={
                "command_id": command_id,
                "qmt_session_id": qmt_session_id,
                "command_state": command_state,
                "broker_token": broker_token,
                "submit_call_started": True,
            },
        )
        return True
