from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskDecision
from bigqmt_autotrader.oms import (
    BrokerEvidenceV1,
    CancelResult,
    OfflineOms,
    OmsRepository,
    SubmitResult,
    current_schema_version,
    connect_database,
    initialize_core_database,
)


class ExecutionCore:
    """Minimal durable execution engine with no Production Runtime dependency."""

    def __init__(self, conn: sqlite3.Connection, oms: OfflineOms) -> None:
        self._conn = conn
        self._oms = oms

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

    @property
    def reconciled(self) -> bool:
        return self._oms.reconciled

    @property
    def database_schema_version(self) -> int:
        return current_schema_version(self._conn)

    def recover(self) -> None:
        self._oms.recover()

    def submit(self, intent: OrderIntent) -> SubmitResult:
        return self._oms.submit_intent(intent)

    def submit_authorized(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        evaluation: object | None = None,
    ) -> SubmitResult:
        return self._oms.submit_authorized_intent(
            intent,
            decision,
            risk_evaluation=evaluation,
        )

    def cancel(self, account_fingerprint: str, client_order_id: str) -> CancelResult:
        return self._oms.cancel_order(account_fingerprint, client_order_id)

    def status(
        self,
        account_fingerprint: str,
        client_order_id: str,
    ) -> OrderStatus:
        return self._oms.repository.get_status(
            account_fingerprint,
            client_order_id,
        )

    def ingest_evidence(self, evidence: BrokerEvidenceV1) -> OrderStatus:
        return self._oms.ingest_broker_evidence(evidence)

    def close(self) -> None:
        try:
            self._oms.close()
        finally:
            self._conn.close()

    def __enter__(self) -> "ExecutionCore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
