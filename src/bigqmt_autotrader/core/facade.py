from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from bigqmt_autotrader.domain import OrderIntent
from bigqmt_autotrader.oms import (
    CancelResult,
    OfflineOms,
    OmsRepository,
    SubmitResult,
    connect_database,
    initialize_core_database,
)


class ExecutionCore:
    """Minimal durable execution engine with no Production Runtime dependency."""

    def __init__(self, conn: sqlite3.Connection, oms: OfflineOms) -> None:
        self.conn = conn
        self.oms = oms

    @classmethod
    def open(
        cls,
        database_path: str | Path,
        driver,
        *,
        clock: Callable[[], datetime] | None = None,
        leader_lease_seconds: int = 30,
    ) -> "ExecutionCore":
        conn = connect_database(database_path)
        try:
            initialize_core_database(conn)
            repository = OmsRepository(conn)
            oms = OfflineOms(
                repository,
                driver,
                clock=clock,
                leader_lease_seconds=leader_lease_seconds,
            )
            return cls(conn, oms)
        except BaseException:
            conn.close()
            raise

    def recover(self) -> None:
        self.oms.recover()

    def submit(self, intent: OrderIntent) -> SubmitResult:
        return self.oms.submit_intent(intent)

    def cancel(self, account_fingerprint: str, client_order_id: str) -> CancelResult:
        return self.oms.cancel_order(account_fingerprint, client_order_id)

    def close(self) -> None:
        try:
            self.oms.close()
        finally:
            self.conn.close()

    def __enter__(self) -> "ExecutionCore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
