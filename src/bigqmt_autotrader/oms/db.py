from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator


CORE_SCHEMA_VERSION = 8
SUPPORTED_SCHEMA_VERSION = 11
MIGRATION_PACKAGE = "bigqmt_autotrader.oms.migrations"


class MigrationError(RuntimeError):
    pass


class FutureSchemaVersion(MigrationError):
    pass


def connect_database(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _ensure_schema_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def current_schema_version(conn: sqlite3.Connection) -> int:
    _ensure_schema_meta(conn)
    row = conn.execute("SELECT MAX(version) AS version FROM schema_meta").fetchone()
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])


def _migration_text(version: int) -> str:
    name = f"{version:04d}_initial.sql" if version == 1 else f"{version:04d}.sql"
    try:
        return resources.files(MIGRATION_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MigrationError(f"missing migration resource for schema version {version}: {name}") from exc


def _apply_migration(conn: sqlite3.Connection, version: int, sql: str) -> None:
    # sqlite3.executescript() manages statements itself, so transaction control is
    # included in the script. A failed migration is explicitly rolled back.
    script = (
        "BEGIN IMMEDIATE;\n"
        + sql
        + "\nINSERT INTO schema_meta(version, applied_at) "
        "VALUES(" + str(version) + ", strftime('%Y-%m-%dT%H:%M:%fZ','now'));\n"
        "COMMIT;\n"
    )
    try:
        conn.executescript(script)
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def _ensure_supported_version(version: int) -> None:
    if version > SUPPORTED_SCHEMA_VERSION:
        raise FutureSchemaVersion(
            f"database schema version {version} is newer than supported "
            f"version {SUPPORTED_SCHEMA_VERSION}"
        )


def initialize_core_database(conn: sqlite3.Connection) -> None:
    """Initialize only Execution Core schema migrations 1..8.

    New Core-only databases stop at schema 8. Existing combined databases at
    schema 9..11 remain readable for backward compatibility and are never
    downgraded.
    """
    version = current_schema_version(conn)
    _ensure_supported_version(version)
    if version < CORE_SCHEMA_VERSION:
        for target in range(version + 1, CORE_SCHEMA_VERSION + 1):
            _apply_migration(conn, target, _migration_text(target))

    rows = conn.execute(
        "SELECT version FROM schema_meta WHERE version <= ? ORDER BY version",
        (CORE_SCHEMA_VERSION,),
    ).fetchall()
    present = [int(row["version"]) for row in rows]
    expected = list(range(1, CORE_SCHEMA_VERSION + 1))
    if present != expected:
        raise MigrationError(
            f"core schema incomplete: expected versions {expected}, got {present}"
        )


def initialize_database(conn: sqlite3.Connection) -> None:
    """Bring a Production Runtime database to the full schema.

    Core-only callers should use initialize_core_database.
    """
    version = current_schema_version(conn)
    _ensure_supported_version(version)

    for target in range(version + 1, SUPPORTED_SCHEMA_VERSION + 1):
        _apply_migration(conn, target, _migration_text(target))

    final = current_schema_version(conn)
    if final != SUPPORTED_SCHEMA_VERSION:
        raise MigrationError(
            f"schema migration incomplete: expected {SUPPORTED_SCHEMA_VERSION}, got {final}"
        )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
