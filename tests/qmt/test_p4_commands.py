import json
import time

import pytest

from bigqmt_autotrader.qmt import (
    QmtCommandConflict,
    QmtCommandError,
    QmtCommandSpool,
    broker_token_for,
)


FP = "sha256:" + "a" * 64


def future_ms(seconds: int = 60) -> int:
    return int(time.time() * 1000) + seconds * 1000


def test_broker_token_is_deterministic_and_qmt_safe_length():
    first = broker_token_for(FP, "cid-001")
    second = broker_token_for(FP, "cid-001")
    other = broker_token_for(FP, "cid-002")
    assert first == second
    assert first != other
    assert first.startswith("BQ")
    assert len(first) == 22
    assert len(first) < 24


def test_publish_submit_is_atomic_and_contains_no_raw_account_id(tmp_path):
    spool = QmtCommandSpool(tmp_path)
    command = spool.publish_submit(
        account_fingerprint=FP,
        client_order_id="cid-001",
        symbol="000001.SZ",
        side="BUY",
        quantity=100,
        limit_price="10.50",
        expires_ms=future_ms(),
        command_id="cmd-001",
        created_ms=int(time.time() * 1000),
    )

    files = list(spool.inbox.glob("*.json"))
    assert len(files) == 1
    assert not list(spool.inbox.glob("*.tmp-*"))
    raw = files[0].read_text(encoding="utf-8")
    frame = json.loads(raw)
    assert frame["command_transport_version"] == "1"
    assert frame["command"]["command_id"] == "cmd-001"
    assert frame["command"]["broker_token"] == command.broker_token
    assert frame["command"]["payload"]["symbol"] == "000001.SZ"
    assert "SECRET_ACCOUNT" not in raw


def test_identical_command_id_is_idempotent_but_conflict_fails_closed(tmp_path):
    spool = QmtCommandSpool(tmp_path)
    created = int(time.time() * 1000)
    expires = created + 60_000
    command = spool.publish_submit(
        account_fingerprint=FP,
        client_order_id="cid-001",
        symbol="000001.SZ",
        side="BUY",
        quantity=100,
        limit_price="10.50",
        expires_ms=expires,
        command_id="cmd-001",
        created_ms=created,
    )
    path = spool.publish(command)
    assert path == spool.inbox / "cmd-001.json"

    with pytest.raises(QmtCommandConflict):
        spool.publish_submit(
            account_fingerprint=FP,
            client_order_id="cid-001",
            symbol="000001.SZ",
            side="BUY",
            quantity=200,
            limit_price="10.50",
            expires_ms=expires,
            command_id="cmd-001",
            created_ms=created,
        )


def test_expired_command_never_enters_inbox(tmp_path):
    spool = QmtCommandSpool(tmp_path)
    now = int(time.time() * 1000)
    with pytest.raises(QmtCommandError):
        spool.publish_submit(
            account_fingerprint=FP,
            client_order_id="cid-expired",
            symbol="000001.SZ",
            side="BUY",
            quantity=100,
            limit_price="10.50",
            expires_ms=now - 1,
            command_id="cmd-expired",
            created_ms=now - 10_000,
        )
    assert not list(spool.inbox.glob("*.json"))


def test_cancel_and_snapshot_commands_have_expected_identity(tmp_path):
    spool = QmtCommandSpool(tmp_path)
    now = int(time.time() * 1000)
    cancel = spool.publish_cancel(
        account_fingerprint=FP,
        client_order_id="cid-001",
        broker_order_id="BROKER-1",
        expires_ms=now + 60_000,
        command_id="cmd-cancel",
        created_ms=now,
    )
    snap = spool.publish_snapshot_request(
        account_fingerprint=FP,
        expires_ms=now + 60_000,
        command_id="cmd-snapshot",
        created_ms=now,
    )
    assert cancel.broker_token == broker_token_for(FP, "cid-001")
    assert snap.client_order_id is None
    assert snap.broker_token is None
    assert len(list(spool.inbox.glob("*.json"))) == 2
