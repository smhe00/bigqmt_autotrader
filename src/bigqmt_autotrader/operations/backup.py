from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3


class BackupVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseBackupResult:
    path: Path
    size_bytes: int
    sha256: str
    schema_version: int


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_meta").fetchone()
    if row is None or row[0] is None:
        raise BackupVerificationError("backup has no schema version")
    return int(row[0])


def _verify_conn(
    conn: sqlite3.Connection,
    *,
    expected_schema_version: int,
) -> int:
    if (
        isinstance(expected_schema_version, bool)
        or not isinstance(expected_schema_version, int)
        or expected_schema_version <= 0
    ):
        raise ValueError("expected_schema_version must be a positive integer")
    row = conn.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        raise BackupVerificationError("sqlite integrity_check failed")
    schema_version = _schema_version(conn)
    if schema_version != expected_schema_version:
        raise BackupVerificationError(
            f"schema version mismatch: expected {expected_schema_version}, got {schema_version}"
        )
    return schema_version


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sync_backup_file(path: Path) -> None:
    """Flush a completed backup through a Windows-compatible descriptor."""
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _sync_parent_directory(
    directory: Path,
    *,
    platform: str | None = None,
) -> bool:
    """Sync published directory metadata where ordinary directory fds exist.

    Windows does not support opening a directory with ``os.open`` for fsync.
    The backup file itself is flushed before the atomic replace; POSIX keeps
    the additional directory-metadata durability barrier.
    """
    platform = os.name if platform is None else platform
    if platform == "nt":
        return False
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(str(directory), flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return True


def verify_database_backup(
    path: str | Path,
    *,
    expected_schema_version: int,
) -> DatabaseBackupResult:
    backup_path = Path(path)
    if not backup_path.is_file():
        raise BackupVerificationError(f"backup does not exist: {backup_path}")
    uri = "file:" + backup_path.resolve().as_posix() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        schema_version = _verify_conn(
            conn,
            expected_schema_version=expected_schema_version,
        )
    except sqlite3.DatabaseError as exc:
        raise BackupVerificationError("backup is not a valid SQLite database") from exc
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass
    return DatabaseBackupResult(
        path=backup_path,
        size_bytes=backup_path.stat().st_size,
        sha256=_sha256_file(backup_path),
        schema_version=schema_version,
    )


def create_database_backup(
    source: sqlite3.Connection,
    destination: str | Path,
    *,
    expected_schema_version: int,
) -> DatabaseBackupResult:
    if not isinstance(source, sqlite3.Connection):
        raise TypeError("source must be sqlite3.Connection")
    destination_path = Path(destination)
    if destination_path.exists():
        raise FileExistsError(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(destination_path.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)

    target: sqlite3.Connection | None = None
    try:
        target = sqlite3.connect(str(temporary))
        source.backup(target)
        target.commit()
        _verify_conn(target, expected_schema_version=expected_schema_version)
        target.close()
        target = None

        _sync_backup_file(temporary)
        os.replace(temporary, destination_path)
        _sync_parent_directory(destination_path.parent)
    except BaseException:
        if target is not None:
            target.close()
        if temporary.exists():
            temporary.unlink()
        raise

    return verify_database_backup(
        destination_path,
        expected_schema_version=expected_schema_version,
    )
