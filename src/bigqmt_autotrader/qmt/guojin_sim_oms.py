from __future__ import annotations

import hashlib
import time

from bigqmt_autotrader.oms.db import connect_database, initialize_database
from bigqmt_autotrader.oms.evidence import EvidenceJournal
from bigqmt_autotrader.oms.leader import LeaderCoordinator
from bigqmt_autotrader.oms.repository import OmsRepository, QmtDurableIdentityConflict

from .commands import QmtCommandType, broker_token_for, decode_command_frame
from .guojin_evidence import GuojinSimEvidenceMapper
from .instances import QmtInstance


AUTHORIZED_GUOJIN_SIM_FINGERPRINT = (
    "sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702"
)
AUTHORIZED_GUOJIN_SIM_BUILD = "p5-simulation-calibration-7"


class GuojinSimOmsRuntime:
    """Instance-pinned durable evidence runtime with no broker mutation API."""

    def __init__(self, instance: QmtInstance) -> None:
        if not guojin_sim_oms_authorized(instance, allow_simulation_mutation=True):
            raise ValueError("guojin_sim OMS runtime authorization failed")
        self.instance = instance
        self.database_path = instance.root / "host_oms.sqlite3"
        self.conn = connect_database(self.database_path)
        initialize_database(self.conn)
        self.repository = OmsRepository(self.conn)
        self._leader = LeaderCoordinator(self.conn)
        self._lease_seconds = 30
        self._lease = self._leader.acquire(
            "qmt-host:" + instance.session_id,
            lease_seconds=self._lease_seconds,
        )
        self._closed = False
        self._last_heartbeat = time.monotonic()
        self.repository.bind_write_guard(self.assert_leader)
        self.evidence_journal = EvidenceJournal(
            self.repository, write_guard=self.assert_leader
        )
        self.mapper = GuojinSimEvidenceMapper(
            account_fingerprint=instance.account_fingerprint
        )
        try:
            self.restore_persisted_identities()
            self.refresh_identities()
        except BaseException:
            self.close()
            raise

    def assert_leader(self) -> None:
        if self._closed:
            raise RuntimeError("guojin_sim OMS runtime is closed")
        self._leader.assert_held(self._lease)

    def maintain(self) -> None:
        if time.monotonic() - self._last_heartbeat >= 10.0:
            self._lease = self._leader.heartbeat(
                self._lease, lease_seconds=self._lease_seconds
            )
            self._last_heartbeat = time.monotonic()

    def restore_persisted_identities(self) -> int:
        """Re-register trusted OMS identities across QMT session rollover."""
        rows = self.conn.execute(
            """
            SELECT account_fingerprint, client_order_id, broker_token, symbol, quantity
            FROM qmt_durable_command_identities ORDER BY command_id
            """
        ).fetchall()
        for row in rows:
            if row["account_fingerprint"] != self.instance.account_fingerprint:
                raise QmtDurableIdentityConflict("OMS database account fingerprint changed")
            token = self.mapper.register_order(
                client_order_id=row["client_order_id"],
                symbol=row["symbol"],
                quantity=int(row["quantity"]),
            )
            if token != row["broker_token"]:
                raise QmtDurableIdentityConflict("persisted OMS broker token mismatch")
        return len(rows)

    def refresh_identities(self) -> int:
        candidates = []
        by_client = {}
        by_command = {}
        validator = GuojinSimEvidenceMapper(
            account_fingerprint=self.instance.account_fingerprint
        )
        for state in ("processed", "unknown"):
            directory = self.instance.root / "commands" / state
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                raw = path.read_bytes()
                command = decode_command_frame(raw)
                if path.name != command.command_id + ".json":
                    raise ValueError("durable command filename/identity mismatch")
                if command.command_type is not QmtCommandType.SUBMIT_LIMIT:
                    continue
                payload = command.payload
                if (
                    command.account_fingerprint != self.instance.account_fingerprint
                    or payload.get("simulation_calibration") is not True
                    or payload.get("expected_qmt_session_id") != self.instance.session_id
                ):
                    continue
                quantity = payload.get("quantity")
                if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity > 100:
                    raise ValueError("durable simulation quantity exceeds Host boundary")
                assert command.client_order_id is not None
                assert command.broker_token is not None
                if command.broker_token != broker_token_for(
                    command.account_fingerprint, command.client_order_id
                ):
                    raise ValueError("durable command broker token mismatch")
                registered_token = validator.register_order(
                    client_order_id=command.client_order_id,
                    symbol=str(payload["symbol"]),
                    quantity=quantity,
                )
                if registered_token != command.broker_token:
                    raise ValueError("mapper token differs from durable command token")
                candidate = dict(
                    command_id=command.command_id,
                    account_fingerprint=command.account_fingerprint,
                    qmt_session_id=self.instance.session_id,
                    client_order_id=command.client_order_id,
                    broker_token=command.broker_token,
                    symbol=str(payload["symbol"]),
                    side=str(payload["side"]),
                    quantity=quantity,
                    limit_price=str(payload["limit_price"]),
                    command_state=state,
                    command_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
                    created_ms=command.created_ms,
                    expires_ms=command.expires_ms,
                )
                previous = by_client.get(command.client_order_id)
                if previous is not None and previous != candidate:
                    raise QmtDurableIdentityConflict("conflicting durable client identity")
                previous = by_command.get(command.command_id)
                if previous is not None and previous != candidate:
                    raise QmtDurableIdentityConflict("conflicting durable command identity")
                by_client[command.client_order_id] = candidate
                by_command[command.command_id] = candidate
                candidates.append(candidate)

        # Detect every file/OMS conflict before importing even the first new
        # identity.  A bad durable record cannot leave a partially imported
        # batch, nor teach the live mapper a callback-derived identity.
        for candidate in candidates:
            row = self.conn.execute(
                """
                SELECT * FROM qmt_durable_command_identities
                WHERE command_id=? OR (account_fingerprint=? AND client_order_id=?)
                   OR (account_fingerprint=? AND broker_token=?)
                """,
                (
                    candidate["command_id"], candidate["account_fingerprint"],
                    candidate["client_order_id"], candidate["account_fingerprint"],
                    candidate["broker_token"],
                ),
            ).fetchone()
            if row is None:
                prior_intent = self.conn.execute(
                    """
                    SELECT 1 FROM order_intents
                    WHERE account_fingerprint=? AND client_order_id=?
                    """,
                    (candidate["account_fingerprint"], candidate["client_order_id"]),
                ).fetchone()
                if prior_intent is not None:
                    raise QmtDurableIdentityConflict(
                        "OMS order exists without matching durable QMT identity"
                    )
                continue
            fields = (
                "command_id", "account_fingerprint", "qmt_session_id",
                "client_order_id", "broker_token", "symbol", "side",
                "quantity", "limit_price", "command_digest", "created_ms",
                "expires_ms",
            )
            if any(row[field] != candidate[field] for field in fields):
                raise QmtDurableIdentityConflict("conflicting durable QMT command identity")
            if row["command_state"] != candidate["command_state"] and not (
                row["command_state"] == "unknown"
                and candidate["command_state"] == "processed"
            ):
                raise QmtDurableIdentityConflict("conflicting durable command state")

        imported = 0
        for candidate in candidates:
            imported += int(self.repository.register_qmt_durable_submit(**candidate))
            self.mapper.register_order(
                client_order_id=candidate["client_order_id"],
                symbol=candidate["symbol"],
                quantity=candidate["quantity"],
            )
        return imported

    def ingest_broker_evidence(self, evidence):
        return self.evidence_journal.ingest(evidence)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._leader.release(self._lease)
        finally:
            self._closed = True
            self.conn.close()


def guojin_sim_oms_authorized(
    instance: QmtInstance | None, *, allow_simulation_mutation: bool
) -> bool:
    return bool(
        instance is not None
        and allow_simulation_mutation
        and instance.instance_id == "guojin_sim"
        and instance.execution_mode == "SIMULATION_CALIBRATION"
        and instance.simulation_only is True
        and instance.trading_enabled is True
        and instance.live_submit is True
        and instance.live_cancel is True
        and instance.account_type == "STOCK"
        and instance.account_fingerprint == AUTHORIZED_GUOJIN_SIM_FINGERPRINT
        and instance.bridge_build == AUTHORIZED_GUOJIN_SIM_BUILD
        and bool(instance.session_id)
    )
