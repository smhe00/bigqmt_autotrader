from decimal import Decimal
from datetime import date, datetime, timezone

import pytest

from bigqmt_autotrader.oms import (
    SUPPORTED_SCHEMA_VERSION,
    connect_database,
    initialize_database,
)
from bigqmt_autotrader.operations import (
    BackupVerificationError,
    create_database_backup,
    verify_database_backup,
)
from bigqmt_autotrader.operations import backup as backup_module
from bigqmt_autotrader.risk import DailyRiskLedger


def populated_db(path):
    conn = connect_database(path)
    initialize_database(conn)
    ledger = DailyRiskLedger(conn)
    ledger.record_pnl_snapshot(
        snapshot_key="pnl-1",
        account_fingerprint="acct",
        trading_date=date(2026, 9, 23),
        daily_pnl=Decimal("12.5"),
        observed_at=datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc),
        source="account_query",
    )
    return conn


def test_online_backup_is_verified_and_independent_from_later_source_changes(tmp_path):
    source = populated_db(tmp_path / "source.sqlite3")
    result = create_database_backup(
        source,
        tmp_path / "backup.sqlite3",
        expected_schema_version=SUPPORTED_SCHEMA_VERSION,
    )

    assert result.schema_version == SUPPORTED_SCHEMA_VERSION
    assert result.size_bytes > 0
    assert result.sha256.startswith("sha256:")

    source.execute(
        "INSERT INTO runtime_sessions(session_id, started_at, reconciled_at) VALUES('later', 'x', NULL)"
    )
    backup = connect_database(result.path)
    assert (
        backup.execute(
            "SELECT COUNT(*) FROM runtime_sessions WHERE session_id='later'"
        ).fetchone()[0]
        == 0
    )


def test_existing_destination_is_never_overwritten(tmp_path):
    source = populated_db(tmp_path / "source.sqlite3")
    destination = tmp_path / "backup.sqlite3"
    destination.write_bytes(b"sentinel")

    with pytest.raises(FileExistsError):
        create_database_backup(
            source,
            destination,
            expected_schema_version=SUPPORTED_SCHEMA_VERSION,
        )
    assert destination.read_bytes() == b"sentinel"


def test_corrupt_backup_fails_verification(tmp_path):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not sqlite")

    with pytest.raises(BackupVerificationError):
        verify_database_backup(
            path,
            expected_schema_version=SUPPORTED_SCHEMA_VERSION,
        )


def test_wrong_schema_expectation_fails_closed(tmp_path):
    source = populated_db(tmp_path / "source.sqlite3")
    result = create_database_backup(
        source,
        tmp_path / "backup.sqlite3",
        expected_schema_version=SUPPORTED_SCHEMA_VERSION,
    )

    with pytest.raises(BackupVerificationError, match="schema version mismatch"):
        verify_database_backup(
            result.path,
            expected_schema_version=SUPPORTED_SCHEMA_VERSION - 1,
        )


def test_backup_file_sync_uses_windows_compatible_update_descriptor(monkeypatch):
    modes = []
    synced = []

    class Handle:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def flush(self):
            synced.append("flush")

        def fileno(self):
            return 37

    class PathProbe:
        def open(self, mode):
            modes.append(mode)
            return Handle()

    monkeypatch.setattr(backup_module.os, "fsync", lambda fd: synced.append(fd))

    backup_module._sync_backup_file(PathProbe())

    assert modes == ["r+b"]
    assert synced == ["flush", 37]


def test_file_sync_failure_prevents_publish_and_cleans_temporary(
    tmp_path, monkeypatch
):
    source = populated_db(tmp_path / "source.sqlite3")
    destination = tmp_path / "backup.sqlite3"

    def fail_sync(path):
        raise OSError("file sync failed")

    monkeypatch.setattr(backup_module, "_sync_backup_file", fail_sync)

    with pytest.raises(OSError, match="file sync failed"):
        create_database_backup(
            source,
            destination,
            expected_schema_version=SUPPORTED_SCHEMA_VERSION,
        )

    assert not destination.exists()
    assert not destination.with_name(destination.name + ".tmp").exists()


def test_atomic_replace_failure_cleans_temporary_without_destination(
    tmp_path, monkeypatch
):
    source = populated_db(tmp_path / "source.sqlite3")
    destination = tmp_path / "backup.sqlite3"

    def fail_replace(source_path, destination_path):
        raise OSError("replace failed")

    monkeypatch.setattr(backup_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        create_database_backup(
            source,
            destination,
            expected_schema_version=SUPPORTED_SCHEMA_VERSION,
        )

    assert not destination.exists()
    assert not destination.with_name(destination.name + ".tmp").exists()


def test_parent_directory_sync_is_posix_only_and_explicit(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        backup_module.os,
        "open",
        lambda path, flags: calls.append((path, flags)) or 41,
    )
    monkeypatch.setattr(backup_module.os, "fsync", lambda fd: calls.append(("fsync", fd)))
    monkeypatch.setattr(backup_module.os, "close", lambda fd: calls.append(("close", fd)))

    assert backup_module._sync_parent_directory(tmp_path, platform="posix") is True
    assert calls[0][0] == str(tmp_path)
    assert calls[-2:] == [("fsync", 41), ("close", 41)]

    calls.clear()
    assert backup_module._sync_parent_directory(tmp_path, platform="nt") is False
    assert calls == []
