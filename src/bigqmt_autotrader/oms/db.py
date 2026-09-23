from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator


SUPPORTED_SCHEMA_VERSION = 10
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


def initialize_database(conn: sqlite3.Connection) -> None:
    """Bring the database to the newest supported forward-only schema.

    Fail closed when the database was created by a newer binary. Downgrades are
    never attempted automatically.
    """
    version = current_schema_version(conn)
    if version > SUPPORTED_SCHEMA_VERSION:
        raise FutureSchemaVersion(
            f"database schema version {version} is newer than supported "
            f"version {SUPPORTED_SCHEMA_VERSION}"
        )

    for target in range(version + 1, SUPPORTED_SCHEMA_VERSION + 1):
        sql = _migration_text(target)
        _apply_migration(conn, target, sql)

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
