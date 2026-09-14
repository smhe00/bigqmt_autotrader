from __future__ import annotations

from pathlib import Path

import pytest

from bigqmt_autotrader.qmt import (
    FileSpoolReceiver,
    QmtHostIngestion,
    QmtIngressBuffer,
    QmtProtocolError,
    encode_transport_frame,
)


ACCOUNT = "sha256:" + "a" * 64
OTHER_ACCOUNT = "sha256:" + "b" * 64


def _event(*, sequence: int, event_type: str = "snapshot", account: str = ACCOUNT, session_id: str = "session-a"):
    payload = (
        {"account": [], "positions": [], "orders": [], "deals": [], "query_errors": []}
        if event_type == "snapshot"
        else {"symbol": "000001.SZ"}
    )
    return {
        "protocol_version": "0.2",
        "session_id": session_id,
        "sequence": sequence,
        "timestamp_ms": 1_700_000_000_000 + sequence,
        "event_type": event_type,
        "source": "active_query" if event_type == "snapshot" else "callback",
        "account_fingerprint": account,
        "account_type": "STOCK",
        "payload": payload,
    }


def _publish(inbox: Path, name: str, event: dict) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    final = inbox / name
    temp = inbox / (name + ".tmp")
    temp.write_bytes(encode_transport_frame(event))
    temp.replace(final)
    return final


def _write_processed(processed: Path, name: str, event: dict) -> Path:
    processed.mkdir(parents=True, exist_ok=True)
    path = processed / name
    path.write_bytes(encode_transport_frame(event))
    return path


def test_file_spool_consumes_valid_frame_and_moves_processed(tmp_path: Path) -> None:
    ingress = QmtIngressBuffer()
    seen = []
    receiver = FileSpoolReceiver(ingress, spool_root=tmp_path, on_event=seen.append)
    _publish(receiver.inbox, "0000000000001_session-a_00000000000000000001.json", _event(sequence=1))

    result = receiver.poll_once()

    assert result.processed == 1
    assert result.rejected == 0
    assert result.pending == 0
    assert len(seen) == 1
    assert seen[0].needs_resync is False
    assert ingress.expected_account_fingerprint == ACCOUNT
    assert not list(receiver.inbox.glob("*.json"))
    assert len(list(receiver.processed.glob("*.json"))) == 1


def test_first_account_is_pinned_and_different_account_is_rejected(tmp_path: Path) -> None:
    ingress = QmtIngressBuffer()
    receiver = FileSpoolReceiver(ingress, spool_root=tmp_path)
    _publish(receiver.inbox, "0001_a.json", _event(sequence=1, account=ACCOUNT))
    receiver.poll_once()
    assert ingress.expected_account_fingerprint == ACCOUNT

    _publish(receiver.inbox, "0002_b.json", _event(sequence=2, account=OTHER_ACCOUNT))
    with pytest.raises(QmtProtocolError):
        ingress.ingest_frame(next(receiver.inbox.glob("*.json")).read_bytes())


def test_gap_remains_fail_closed_until_clean_snapshot(tmp_path: Path) -> None:
    ingress = QmtIngressBuffer()
    seen = []
    receiver = FileSpoolReceiver(ingress, spool_root=tmp_path, on_event=seen.append)

    _publish(receiver.inbox, "0001.json", _event(sequence=1))
    receiver.poll_once()
    assert seen[-1].needs_resync is False

    _publish(receiver.inbox, "0003.json", _event(sequence=3, event_type="position"))
    receiver.poll_once()
    assert seen[-1].disposition.value == "GAP"
    assert seen[-1].needs_resync is True

    _publish(receiver.inbox, "0004.json", _event(sequence=4))
    receiver.poll_once()
    assert seen[-1].needs_resync is False


def test_malformed_frame_moves_to_rejected(tmp_path: Path) -> None:
    ingress = QmtIngressBuffer()
    receiver = FileSpoolReceiver(ingress, spool_root=tmp_path)
    bad = receiver.inbox / "bad.json"
    bad.write_bytes(b"not-json\n")

    result = receiver.poll_once()

    assert result.rejected == 1
    assert result.processed == 0
    assert not bad.exists()
    assert len(list(receiver.rejected.iterdir())) == 1


def test_restart_replays_latest_clean_snapshot_and_continues_sequence(tmp_path: Path) -> None:
    first_ingress = QmtIngressBuffer()
    first_host = QmtHostIngestion()
    first = FileSpoolReceiver(
        first_ingress,
        spool_root=tmp_path,
        on_event=first_host.handle,
    )
    _publish(first.inbox, "0001.json", _event(sequence=1, event_type="bridge_ready"))
    _publish(first.inbox, "0002.json", _event(sequence=2, event_type="snapshot"))
    _publish(first.inbox, "0003.json", _event(sequence=3, event_type="account"))
    consumed = first.poll_once(max_files=10)
    assert consumed.processed == 3
    assert first_host.read_model.healthy is True

    restarted_ingress = QmtIngressBuffer()
    restarted_host = QmtHostIngestion()
    restarted = FileSpoolReceiver(
        restarted_ingress,
        spool_root=tmp_path,
        on_event=restarted_host.handle,
    )
    replay = restarted.replay_processed_from_latest_clean_snapshot()

    assert replay.snapshot_found is True
    assert replay.replayed == 2
    assert replay.session_id == "session-a"
    assert replay.last_sequence == 3
    assert replay.account_fingerprint == ACCOUNT
    assert restarted_ingress.last_sequence == 3
    assert restarted_host.read_model.healthy is True
    assert len(list(restarted.processed.glob("*.json"))) == 3

    _publish(restarted.inbox, "0004.json", _event(sequence=4, event_type="account"))
    resumed = restarted.poll_once()
    assert resumed.processed == 1
    assert restarted_ingress.last_sequence == 4
    assert restarted_ingress.needs_resync is False
    assert restarted_host.read_model.healthy is True


def test_restart_replay_uses_newest_clean_snapshot_not_older_account(tmp_path: Path) -> None:
    ingress = QmtIngressBuffer()
    host = QmtHostIngestion()
    receiver = FileSpoolReceiver(ingress, spool_root=tmp_path, on_event=host.handle)

    _write_processed(
        receiver.processed,
        "1700000000001_old_00000000000000000001.json",
        _event(sequence=1, account=OTHER_ACCOUNT, session_id="old-session"),
    )
    current_snapshot = _event(sequence=2, account=ACCOUNT, session_id="session-a")
    current_snapshot["timestamp_ms"] = 1_700_000_001_000
    _write_processed(
        receiver.processed,
        "1700000001000_session-a_00000000000000000002.json",
        current_snapshot,
    )
    current_account = _event(sequence=3, event_type="account", account=ACCOUNT, session_id="session-a")
    current_account["timestamp_ms"] = 1_700_000_001_001
    _write_processed(
        receiver.processed,
        "1700000001001_session-a_00000000000000000003.json",
        current_account,
    )

    replay = receiver.replay_processed_from_latest_clean_snapshot()

    assert replay.snapshot_found is True
    assert replay.replayed == 2
    assert ingress.expected_account_fingerprint == ACCOUNT
    assert ingress.session_id == "session-a"
    assert ingress.last_sequence == 3
    assert host.read_model.healthy is True


def test_restart_replay_without_clean_snapshot_is_noop(tmp_path: Path) -> None:
    receiver = FileSpoolReceiver(QmtIngressBuffer(), spool_root=tmp_path)
    _write_processed(
        receiver.processed,
        "0001.json",
        _event(sequence=1, event_type="account"),
    )

    replay = receiver.replay_processed_from_latest_clean_snapshot()

    assert replay.snapshot_found is False
    assert replay.replayed == 0
    assert receiver.ingress.last_sequence == 0
