from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .protocol import QmtEvent
from .receiver import IngressResult


@dataclass(frozen=True)
class QmtSnapshotView:
    account_fingerprint: str
    account_type: str | None
    session_id: str
    sequence: int
    timestamp_ms: int
    account: tuple[Mapping[str, Any], ...]
    positions: tuple[Mapping[str, Any], ...]
    orders: tuple[Mapping[str, Any], ...]
    deals: tuple[Mapping[str, Any], ...]
    healthy: bool


class QmtReadModel:
    """Host-side current broker view.

    Broker-state callbacks incrementally update an already synchronized view.
    Non-broker bridge events such as command_result still advance sequence/time
    continuity but cannot mutate account/position/order/deal state.
    """

    def __init__(self) -> None:
        self._view: QmtSnapshotView | None = None
        self._needs_resync = True
        self._linked_accounts: tuple[Mapping[str, Any], ...] = ()

    @property
    def view(self) -> QmtSnapshotView | None:
        return self._view

    @property
    def healthy(self) -> bool:
        return self._view is not None and self._view.healthy and not self._needs_resync

    @property
    def linked_accounts(self) -> tuple[Mapping[str, Any], ...]:
        """Latest broker-agnostic read-only account capability observations."""
        return self._linked_accounts

    def apply(self, result: IngressResult) -> QmtSnapshotView | None:
        event = result.event
        self._needs_resync = result.needs_resync

        if event.event_type == "account_capabilities":
            self._linked_accounts = tuple(
                {
                    **dict(record),
                    "account": [dict(row) for row in record["account"]],
                    "positions": [dict(row) for row in record["positions"]],
                    "query_errors": [dict(row) for row in record["query_errors"]],
                }
                for record in event.payload["accounts"]
            )
            if self._view is not None:
                self._view = self._replace(
                    sequence=event.sequence,
                    timestamp_ms=event.timestamp_ms,
                )
            return self._view

        if event.event_type == "snapshot":
            self._view = self._from_snapshot(event, healthy=not result.needs_resync)
            return self._view

        if self._view is None:
            return None

        # Callback events may incrementally enrich an already synchronized view,
        # but never make an unhealthy stream healthy.
        if event.event_type == "account":
            account = (dict(event.payload),)
            self._view = self._replace(account=account, sequence=event.sequence, timestamp_ms=event.timestamp_ms)
        elif event.event_type == "position":
            positions = self._upsert_by_symbol(self._view.positions, event.payload)
            self._view = self._replace(positions=positions, sequence=event.sequence, timestamp_ms=event.timestamp_ms)
        elif event.event_type == "order":
            orders = self._append_event(self._view.orders, event.payload)
            self._view = self._replace(orders=orders, sequence=event.sequence, timestamp_ms=event.timestamp_ms)
        elif event.event_type == "deal":
            deals = self._append_event(self._view.deals, event.payload)
            self._view = self._replace(deals=deals, sequence=event.sequence, timestamp_ms=event.timestamp_ms)
        elif event.event_type in {
            "command_result",
            "bridge_ready",
            "bridge_error",
            "instrument_capabilities",
        }:
            self._view = self._replace(sequence=event.sequence, timestamp_ms=event.timestamp_ms)
        return self._view

    def _replace(self, **changes: Any) -> QmtSnapshotView:
        assert self._view is not None
        values = {
            "account_fingerprint": self._view.account_fingerprint,
            "account_type": self._view.account_type,
            "session_id": self._view.session_id,
            "sequence": self._view.sequence,
            "timestamp_ms": self._view.timestamp_ms,
            "account": self._view.account,
            "positions": self._view.positions,
            "orders": self._view.orders,
            "deals": self._view.deals,
            "healthy": not self._needs_resync,
        }
        values.update(changes)
        values["healthy"] = not self._needs_resync
        return QmtSnapshotView(**values)

    @staticmethod
    def _from_snapshot(event: QmtEvent, *, healthy: bool) -> QmtSnapshotView:
        payload = event.payload
        return QmtSnapshotView(
            account_fingerprint=event.account_fingerprint,
            account_type=event.account_type,
            session_id=event.session_id,
            sequence=event.sequence,
            timestamp_ms=event.timestamp_ms,
            account=tuple(dict(row) for row in payload["account"]),
            positions=tuple(dict(row) for row in payload["positions"]),
            orders=tuple(dict(row) for row in payload["orders"]),
            deals=tuple(dict(row) for row in payload["deals"]),
            healthy=healthy,
        )

    @staticmethod
    def _upsert_by_symbol(
        rows: tuple[Mapping[str, Any], ...],
        payload: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        symbol = payload.get("symbol")
        if not symbol:
            return tuple(rows) + (dict(payload),)
        updated = []
        replaced = False
        for row in rows:
            if row.get("symbol") == symbol:
                updated.append(dict(payload))
                replaced = True
            else:
                updated.append(dict(row))
        if not replaced:
            updated.append(dict(payload))
        return tuple(updated)

    @staticmethod
    def _append_event(
        rows: tuple[Mapping[str, Any], ...],
        payload: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(rows) + (dict(payload),)
