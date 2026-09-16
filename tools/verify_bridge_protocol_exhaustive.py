from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
import tempfile

from bigqmt_autotrader.qmt.commands import (
    QmtCommand,
    QmtCommandConflict,
    QmtCommandError,
    QmtCommandSpool,
)
from bigqmt_autotrader.qmt.protocol import (
    BRIDGE_PROTOCOL_VERSION,
    IngressDisposition,
    QmtEvent,
)
from bigqmt_autotrader.qmt.receiver import (
    QmtIngressBuffer,
    QmtIngressIdentityError,
)


FP = "sha256:" + "a" * 64
OTHER_FP = "sha256:" + "b" * 64
INSTANCE = "guojin"


@dataclass
class Oracle:
    session_id: str | None = None
    last_sequence: int = 0
    needs_resync: bool = True


@dataclass(frozen=True)
class Case:
    instance_id: str
    fingerprint: str
    session_id: str
    sequence: int
    clean_snapshot: bool


def make_event(case: Case) -> QmtEvent:
    if case.clean_snapshot:
        event_type = "snapshot"
        payload = {
            "account": [],
            "positions": [],
            "orders": [],
            "deals": [],
            "query_errors": [],
        }
    else:
        event_type = "account"
        payload = {"status": "ok"}
    return QmtEvent(
        protocol_version=BRIDGE_PROTOCOL_VERSION,
        session_id=case.session_id,
        sequence=case.sequence,
        timestamp_ms=1_700_000_000_000 + case.sequence,
        event_type=event_type,
        source="bridge-contract-check",
        account_fingerprint=case.fingerprint,
        account_type="STOCK",
        payload=payload,
        terminal_instance_id=case.instance_id,
    )


def oracle_ingest(state: Oracle, case: Case):
    if case.instance_id != INSTANCE or case.fingerprint != FP:
        return "IDENTITY_ERROR", state

    if state.session_id != case.session_id:
        state.session_id = case.session_id
        state.last_sequence = 0
        state.needs_resync = True

    if case.sequence <= state.last_sequence:
        return IngressDisposition.DUPLICATE, state

    disposition = IngressDisposition.ACCEPTED
    if state.last_sequence and case.sequence != state.last_sequence + 1:
        disposition = IngressDisposition.GAP
        state.needs_resync = True

    state.last_sequence = case.sequence
    if case.clean_snapshot:
        state.needs_resync = False
    return disposition, state


def verify_ingress_matrix() -> None:
    alphabet = [
        Case(instance_id, fingerprint, session_id, sequence, clean)
        for instance_id, fingerprint, session_id, sequence, clean in product(
            (INSTANCE, "other"),
            (FP, OTHER_FP),
            ("s1", "s2"),
            (1, 2, 3),
            (False, True),
        )
    ]

    # Length two is enough to exercise duplicate, gap, clean-snapshot recovery,
    # session switch, and identity rejection from both initial and non-initial states.
    checked = 0
    for sequence_cases in product(alphabet, repeat=2):
        actual = QmtIngressBuffer(
            expected_account_fingerprint=FP,
            expected_terminal_instance_id=INSTANCE,
        )
        expected = Oracle()
        for case in sequence_cases:
            expected_outcome, expected = oracle_ingest(expected, case)
            try:
                actual_outcome = actual.ingest(make_event(case))
            except QmtIngressIdentityError:
                if expected_outcome != "IDENTITY_ERROR":
                    raise AssertionError("unexpected identity rejection")
            else:
                if expected_outcome == "IDENTITY_ERROR":
                    raise AssertionError("identity mismatch was accepted")
                assert actual_outcome.disposition is expected_outcome
                assert actual_outcome.needs_resync is expected.needs_resync
                assert actual.session_id == expected.session_id
                assert actual.last_sequence == expected.last_sequence
            checked += 1
    print(f"Bridge event ingress finite matrix: PASS ({checked} transitions)")


def verify_command_spool_contract() -> None:
    with tempfile.TemporaryDirectory() as temp:
        spool = QmtCommandSpool(Path(temp))
        first = spool.publish_submit(
            account_fingerprint=FP,
            client_order_id="cid-001",
            symbol="000001.SZ",
            side="BUY",
            quantity=100,
            limit_price="10.00",
            created_ms=1_700_000_000_000,
            expires_ms=4_700_000_000_000,
            command_id="contract-command-001",
        )
        first_path = spool.inbox / (first.command_id + ".json")
        original = first_path.read_bytes()

        same = spool.publish(first)
        assert same == first_path
        assert same.read_bytes() == original
        assert len(list(spool.inbox.glob("*.json"))) == 1

        conflict = QmtCommand(
            command_id=first.command_id,
            created_ms=first.created_ms,
            expires_ms=first.expires_ms,
            account_fingerprint=FP,
            command_type=first.command_type,
            client_order_id="cid-001",
            broker_token=first.broker_token,
            payload={
                "symbol": "000001.SZ",
                "side": "BUY",
                "quantity": 200,
                "limit_price": "10.00",
            },
        )
        try:
            spool.publish(conflict)
        except QmtCommandConflict:
            pass
        else:
            raise AssertionError("conflicting command_id content was accepted")
        assert first_path.read_bytes() == original

        # Public publish path must fail closed before an already-expired command
        # can enter commands/inbox.
        try:
            spool.publish_submit(
                account_fingerprint=FP,
                client_order_id="cid-expired",
                symbol="000001.SZ",
                side="BUY",
                quantity=100,
                limit_price="10.00",
                created_ms=1,
                expires_ms=2,
                command_id="expired-command",
            )
        except QmtCommandError:
            pass
        else:
            raise AssertionError("expired command was published")

    print("Bridge command spool idempotency/conflict/expiry: PASS")


def main() -> int:
    verify_ingress_matrix()
    verify_command_spool_contract()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
