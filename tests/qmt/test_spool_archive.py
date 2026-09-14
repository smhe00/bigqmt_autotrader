from datetime import datetime
import gzip
import json
from pathlib import Path

import pytest

from bigqmt_autotrader.qmt import (
    ArchiveIntegrityError,
    DailySpoolArchiver,
    FileSpoolReceiver,
    QmtIngressBuffer,
    SHANGHAI_TZ,
    encode_transport_frame,
)


FP = "sha256:" + "a" * 64
DAY = "2026-09-14"


def ts(hour: int, minute: int, second: int = 0, millis: int = 0) -> int:
    value = datetime(2026, 9, 14, hour, minute, second, millis * 1000, tzinfo=SHANGHAI_TZ)
    return int(value.timestamp() * 1000)


def event(
    sequence: int,
    *,
    event_type: str = "snapshot",
    timestamp_ms: int | None = None,
    session_id: str = "session-a",
):
    if timestamp_ms is None:
        timestamp_ms = ts(15, 0, sequence)
    if event_type == "snapshot":
        payload = {
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "account": [{"balance": "1000", "available_cash": "800"}],
            "positions": [{"symbol": "000001.SZ", "quantity": 100}],
            "orders": [],
            "deals": [],
            "query_errors": [],
        }
        source = "active_query"
    else:
        payload = {"symbol": "000001.SZ", "quantity": 100 + sequence}
        source = "callback"
    return {
        "protocol_version": "0.2",
        "session_id": session_id,
        "sequence": sequence,
        "timestamp_ms": timestamp_ms,
        "event_type": event_type,
        "source": source,
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "payload": payload,
    }


def account_event(sequence: int, *, balance: str = "1000", available_cash: str = "800") -> dict:
    value = event(sequence, event_type="account", timestamp_ms=ts(15, 0, sequence))
    value["payload"] = {"balance": balance, "available_cash": available_cash}
    return value


def position_event(
    sequence: int,
    *,
    quantity: int = 100,
    symbol: str = "000001.SZ",
    timestamp_ms: int | None = None,
) -> dict:
    if timestamp_ms is None:
        timestamp_ms = ts(15, 0, sequence)
    value = event(sequence, event_type="position", timestamp_ms=timestamp_ms)
    value["payload"] = {"symbol": symbol, "quantity": quantity}
    return value


def full_position_row(
    *,
    symbol: str = "204001.SH",
    quantity: int = 1000,
    open_price: str = "1.4150000000000003",
    market_value: str = "1000.0",
) -> dict:
    return {
        "symbol": symbol,
        "quantity": quantity,
        "sellable_quantity": quantity,
        "frozen_quantity": 0,
        "on_road_quantity": 0,
        "market_value": market_value,
        "last_price": "1.4150000000000003",
        "open_price": open_price,
        "trading_day": "20260914",
    }


def write_inbox(root: Path, value: dict) -> Path:
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{value['timestamp_ms']:013d}_{value['session_id']}_{value['sequence']:020d}.json"
    path.write_bytes(encode_transport_frame(value))
    return path


def write_processed(root: Path, value: dict, *, suffix: str = "") -> Path:
    processed = root / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    path = processed / (
        f"{value['timestamp_ms']:013d}_{value['session_id']}_{value['sequence']:020d}{suffix}.json"
    )
    path.write_bytes(encode_transport_frame(value))
    return path


def consume(root: Path, values: list[dict]) -> FileSpoolReceiver:
    receiver = FileSpoolReceiver(
        QmtIngressBuffer(expected_account_fingerprint=FP),
        spool_root=root,
    )
    for value in values:
        write_inbox(root, value)
    result = receiver.poll_once(max_files=100)
    assert result.processed == len(values)
    assert result.quarantined == 0
    return receiver


def test_malformed_spool_file_moves_to_quarantine(tmp_path: Path):
    receiver = FileSpoolReceiver(
        QmtIngressBuffer(expected_account_fingerprint=FP),
        spool_root=tmp_path,
    )
    bad = receiver.inbox / f"{ts(10, 0):013d}_bad_00000000000000000001.json"
    bad.write_bytes(b"not-json\n")

    result = receiver.poll_once()

    assert result.processed == 0
    assert result.quarantined == 1
    assert not bad.exists()
    assert (receiver.quarantine / bad.name).exists()


def test_daily_archive_commits_then_deletes_small_files(tmp_path: Path):
    values = [
        event(1, timestamp_ms=ts(14, 59, 0)),
        event(2, event_type="position", timestamp_ms=ts(14, 59, 30)),
        event(3, timestamp_ms=ts(15, 0, 0)),
    ]
    receiver = consume(tmp_path, values)
    assert len(list(receiver.processed.glob("*.json"))) == 3

    archiver = DailySpoolArchiver(spool_root=tmp_path)
    result = archiver.archive_day(
        DAY,
        quiet_seconds=300,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "archived"
    assert result.event_count == 3
    assert result.deleted_files == 3
    assert not list(receiver.processed.glob("*.json"))

    archive = tmp_path / "archive" / f"{DAY}_events.jsonl.gz"
    manifest = tmp_path / "archive" / f"{DAY}_manifest.json"
    checkpoint = tmp_path / "checkpoints" / f"{DAY}.json"
    assert archive.exists() and manifest.exists() and checkpoint.exists()

    with gzip.open(archive, "rb") as handle:
        lines = list(handle)
    assert len(lines) == 3
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    assert meta["event_count"] == 3
    assert meta["source_file_count"] == 3
    assert meta["final_snapshot"]["sequence"] == 3
    assert meta["trailing_identical_account_heartbeats"] == 0
    assert meta["trailing_identical_position_callbacks"] == 0
    assert meta["quiet_anchor_timestamp_ms"] == ts(15, 0, 0)
    assert meta["archive_sha256"] == result.archive_sha256
    committed = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert committed["status"] == "COMMITTED"


def test_archive_allows_identical_account_heartbeat_after_clean_snapshot(tmp_path: Path):
    values = [
        event(1, timestamp_ms=ts(15, 0, 0)),
        account_event(2),
    ]
    receiver = consume(tmp_path, values)
    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=0,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "archived"
    assert not list(receiver.processed.glob("*.json"))
    manifest = json.loads(
        (tmp_path / "archive" / f"{DAY}_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["final_snapshot"]["sequence"] == 1
    assert manifest["trailing_identical_account_heartbeats"] == 1
    assert manifest["trailing_identical_position_callbacks"] == 0


def test_identical_account_heartbeat_does_not_reset_quiet_period(tmp_path: Path):
    snapshot = event(1, timestamp_ms=ts(15, 0, 0))
    heartbeat = account_event(2)
    heartbeat["timestamp_ms"] = ts(15, 19, 0)
    receiver = consume(tmp_path, [snapshot, heartbeat])

    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=300,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "archived"
    assert not list(receiver.processed.glob("*.json"))
    manifest = json.loads(
        (tmp_path / "archive" / f"{DAY}_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["last_timestamp_ms"] == ts(15, 19, 0)
    assert manifest["quiet_anchor_timestamp_ms"] == ts(15, 0, 0)
    assert manifest["trailing_identical_account_heartbeats"] == 1
    assert manifest["trailing_identical_position_callbacks"] == 0


def test_archive_allows_identical_position_callback_after_clean_snapshot(tmp_path: Path):
    values = [
        event(1, timestamp_ms=ts(15, 0, 0)),
        position_event(2),
    ]
    receiver = consume(tmp_path, values)
    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=0,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "archived"
    assert not list(receiver.processed.glob("*.json"))
    manifest = json.loads(
        (tmp_path / "archive" / f"{DAY}_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["final_snapshot"]["sequence"] == 1
    assert manifest["trailing_identical_account_heartbeats"] == 0
    assert manifest["trailing_identical_position_callbacks"] == 1


def test_archive_allows_zero_open_price_when_all_other_position_fields_match(tmp_path: Path):
    snapshot = event(1, timestamp_ms=ts(15, 0, 0))
    snapshot_position = full_position_row()
    snapshot["payload"]["positions"] = [snapshot_position]
    replay = position_event(2, symbol="204001.SH", timestamp_ms=ts(15, 19, 0))
    replay["payload"] = dict(snapshot_position)
    replay["payload"]["open_price"] = "0.0"

    receiver = consume(tmp_path, [snapshot, replay])
    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=300,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "archived"
    assert not list(receiver.processed.glob("*.json"))
    manifest = json.loads(
        (tmp_path / "archive" / f"{DAY}_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["final_snapshot"]["sequence"] == 1
    assert manifest["quiet_anchor_timestamp_ms"] == ts(15, 0, 0)
    assert manifest["trailing_identical_position_callbacks"] == 1


def test_zero_open_price_does_not_mask_other_position_change(tmp_path: Path):
    snapshot = event(1, timestamp_ms=ts(15, 0, 0))
    snapshot_position = full_position_row()
    snapshot["payload"]["positions"] = [snapshot_position]
    changed = position_event(2, symbol="204001.SH")
    changed["payload"] = dict(snapshot_position)
    changed["payload"]["open_price"] = "0.0"
    changed["payload"]["market_value"] = "999.0"

    receiver = consume(tmp_path, [snapshot, changed])
    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=0,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "not_ready"
    assert result.reasons == ("final_snapshot_missing",)
    assert len(list(receiver.processed.glob("*.json"))) == 2


def test_nonzero_open_price_change_still_requires_new_snapshot(tmp_path: Path):
    snapshot = event(1, timestamp_ms=ts(15, 0, 0))
    snapshot_position = full_position_row()
    snapshot["payload"]["positions"] = [snapshot_position]
    changed = position_event(2, symbol="204001.SH")
    changed["payload"] = dict(snapshot_position)
    changed["payload"]["open_price"] = "1.4"

    receiver = consume(tmp_path, [snapshot, changed])
    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=0,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "not_ready"
    assert result.reasons == ("final_snapshot_missing",)
    assert len(list(receiver.processed.glob("*.json"))) == 2


def test_identical_position_callback_does_not_reset_quiet_period(tmp_path: Path):
    snapshot = event(1, timestamp_ms=ts(15, 0, 0))
    replay = position_event(2, timestamp_ms=ts(15, 19, 0))
    receiver = consume(tmp_path, [snapshot, replay])

    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=300,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "archived"
    assert not list(receiver.processed.glob("*.json"))
    manifest = json.loads(
        (tmp_path / "archive" / f"{DAY}_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["last_timestamp_ms"] == ts(15, 19, 0)
    assert manifest["quiet_anchor_timestamp_ms"] == ts(15, 0, 0)
    assert manifest["trailing_identical_position_callbacks"] == 1


def test_archive_requires_new_snapshot_after_real_account_change(tmp_path: Path):
    values = [
        event(1, timestamp_ms=ts(15, 0, 0)),
        account_event(2, available_cash="700"),
    ]
    receiver = consume(tmp_path, values)
    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=0,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "not_ready"
    assert result.reasons == ("final_snapshot_missing",)
    assert len(list(receiver.processed.glob("*.json"))) == 2


def test_archive_requires_new_snapshot_after_real_position_change(tmp_path: Path):
    values = [
        event(1, timestamp_ms=ts(15, 0, 0)),
        position_event(2, quantity=101),
    ]
    receiver = consume(tmp_path, values)
    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=0,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "not_ready"
    assert result.reasons == ("final_snapshot_missing",)
    assert len(list(receiver.processed.glob("*.json"))) == 2


def test_archive_requires_clean_final_snapshot_and_quiet_period(tmp_path: Path):
    values = [
        event(1, timestamp_ms=ts(14, 59, 0)),
        event(2, event_type="position", timestamp_ms=ts(15, 0, 0)),
    ]
    receiver = consume(tmp_path, values)
    archiver = DailySpoolArchiver(spool_root=tmp_path)

    too_early = archiver.archive_day(DAY, quiet_seconds=300, now_ms=ts(15, 2, 0))
    assert too_early.status == "not_ready"
    assert "quiet_period" in too_early.reasons
    assert "final_snapshot_missing" in too_early.reasons

    later = archiver.archive_day(DAY, quiet_seconds=300, now_ms=ts(15, 20, 0))
    assert later.status == "not_ready"
    assert later.reasons == ("final_snapshot_missing",)
    assert len(list(receiver.processed.glob("*.json"))) == 2
    assert not (tmp_path / "checkpoints" / f"{DAY}.json").exists()


def test_archive_refuses_sequence_gap_even_if_snapshot_resynced(tmp_path: Path):
    values = [
        event(1, timestamp_ms=ts(14, 59, 0)),
        event(3, timestamp_ms=ts(15, 0, 0)),
    ]
    consume(tmp_path, values)
    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=0,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "not_ready"
    assert "sequence_gap" in result.reasons
    assert len(list((tmp_path / "processed").glob("*.json"))) == 2


def test_archive_refuses_day_with_quarantine_file(tmp_path: Path):
    consume(tmp_path, [event(1, timestamp_ms=ts(15, 0, 0))])
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir(exist_ok=True)
    (quarantine / f"{ts(14, 30):013d}_broken_00000000000000000002.json").write_bytes(b"broken")

    result = DailySpoolArchiver(spool_root=tmp_path).archive_day(
        DAY,
        quiet_seconds=0,
        now_ms=ts(15, 20, 0),
    )

    assert result.status == "not_ready"
    assert "quarantine_present" in result.reasons
    assert list((tmp_path / "processed").glob("*.json"))


def test_committed_checkpoint_recovers_cleanup_after_crash(tmp_path: Path):
    value = event(1, timestamp_ms=ts(15, 0, 0))
    consume(tmp_path, [value])
    archiver = DailySpoolArchiver(spool_root=tmp_path)
    first = archiver.archive_day(DAY, quiet_seconds=0, now_ms=ts(15, 20, 0))
    assert first.status == "archived"

    manifest = json.loads((tmp_path / "archive" / f"{DAY}_manifest.json").read_text(encoding="utf-8"))
    source_name = manifest["source_files"][0]
    recreated = tmp_path / "processed" / source_name
    recreated.write_bytes(encode_transport_frame(value))

    recovered = archiver.archive_day(DAY, quiet_seconds=0, now_ms=ts(15, 30, 0))
    assert recovered.status == "already_archived"
    assert recovered.deleted_files == 1
    assert not recreated.exists()


def test_corrupt_committed_archive_never_deletes_recoverable_source(tmp_path: Path):
    value = event(1, timestamp_ms=ts(15, 0, 0))
    consume(tmp_path, [value])
    archiver = DailySpoolArchiver(spool_root=tmp_path)
    first = archiver.archive_day(DAY, quiet_seconds=0, now_ms=ts(15, 20, 0))
    assert first.status == "archived"

    manifest = json.loads((tmp_path / "archive" / f"{DAY}_manifest.json").read_text(encoding="utf-8"))
    source_name = manifest["source_files"][0]
    recoverable = tmp_path / "processed" / source_name
    recoverable.write_bytes(encode_transport_frame(value))
    (tmp_path / "archive" / f"{DAY}_events.jsonl.gz").write_bytes(b"corrupted")

    with pytest.raises(ArchiveIntegrityError):
        archiver.archive_day(DAY, quiet_seconds=0, now_ms=ts(15, 30, 0))
    assert recoverable.exists()


def test_late_event_after_commit_is_not_silently_deleted(tmp_path: Path):
    first_value = event(1, timestamp_ms=ts(15, 0, 0))
    consume(tmp_path, [first_value])
    archiver = DailySpoolArchiver(spool_root=tmp_path)
    committed = archiver.archive_day(DAY, quiet_seconds=0, now_ms=ts(15, 20, 0))
    assert committed.status == "archived"

    late = event(2, event_type="position", timestamp_ms=ts(15, 5, 0))
    late_path = write_processed(tmp_path, late, suffix=".late")
    result = archiver.archive_day(DAY, quiet_seconds=0, now_ms=ts(15, 30, 0))

    assert result.status == "late_events"
    assert result.reasons == ("late_events_after_commit",)
    assert late_path.exists()
