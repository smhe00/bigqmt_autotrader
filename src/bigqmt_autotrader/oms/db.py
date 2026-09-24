from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator


CORE_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSION = 11
MIGRATION_PACKAGE = "bigqmt_autotrader.oms.migrations"
CORE_MIGRATION_PACKAGE = "bigqmt_autotrader.oms.core_migrations"


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


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _ensure_schema_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _ensure_core_schema_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core_schema_meta (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _existing_legacy_schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_meta"):
        return 0
    row = conn.execute("SELECT MAX(version) AS version FROM schema_meta").fetchone()
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])


def current_schema_version(conn: sqlite3.Connection) -> int:
    _ensure_schema_meta(conn)
    row = conn.execute("SELECT MAX(version) AS version FROM schema_meta").fetchone()
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])


def current_core_schema_version(conn: sqlite3.Connection) -> int:
    _ensure_core_schema_meta(conn)
    row = conn.execute("SELECT MAX(version) AS version FROM core_schema_meta").fetchone()
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])


def _migration_text(version: int, package: str = MIGRATION_PACKAGE) -> str:
    name = f"{version:04d}_initial.sql" if version == 1 else f"{version:04d}.sql"
    try:
        return resources.files(package).joinpath(name).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MigrationError(
            f"missing migration resource for schema version {version}: {package}/{name}"
        ) from exc


def _apply_migration(
    conn: sqlite3.Connection,
    version: int,
    sql: str,
    meta_table: str = "schema_meta",
) -> None:
    if meta_table not in {"schema_meta", "core_schema_meta"}:
        raise ValueError("unsupported migration metadata table")
    script = (
        "BEGIN IMMEDIATE;\n"
        + sql
        + f"\nINSERT INTO {meta_table}(version, applied_at) "
        + "VALUES(" + str(version) + ", strftime('%Y-%m-%dT%H:%M:%fZ','now'));\n"
        + "COMMIT;\n"
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


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _validate_core_shape(conn: sqlite3.Connection) -> None:
    required_tables = {
        "order_intents",
        "broker_orders",
        "risk_decisions",
        "order_events",
        "runtime_sessions",
        "oms_leader",
        "broker_evidence_keys",
        "broker_evidence_observations",
    }
    present = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IS NOT NULL"
        )
    }
    missing = sorted(required_tables - present)
    if missing:
        raise MigrationError("core schema missing tables: " + ", ".join(missing))

    required_columns = {
        "broker_orders": {
            "cancel_call_started",
            "cancel_outcome_resolved",
        },
        "broker_evidence_keys": {
            "account_fingerprint",
            "semantic_digest",
        },
        "broker_evidence_observations": {
            "source_kind",
            "mapper_profile",
            "semantic_digest",
            "broker_token",
            "order_ref",
            "trade_id",
            "raw_payload_ref",
            "raw_status_json",
            "route_account_type",
            "route_account_fingerprint",
        },
    }
    for table, required in required_columns.items():
        missing_columns = sorted(required - _column_names(conn, table))
        if missing_columns:
            raise MigrationError(
                f"core schema table {table} missing columns: "
                + ", ".join(missing_columns)
            )


def initialize_core_database(conn: sqlite3.Connection) -> None:
    """Initialize the broker-neutral Execution Core schema.

    Fresh Core-only databases use an independent Core schema lineage and never
    create QMT, Risk Runtime, Operations, or Web tables. Historical combined
    databases at legacy schema >=7 are recognized in place and marked Core-v1
    compatible after their Core shape is validated; they are never downgraded.
    """
    legacy_version = _existing_legacy_schema_version(conn)
    _ensure_supported_version(legacy_version)
    _ensure_core_schema_meta(conn)

    core_version = current_core_schema_version(conn)
    if core_version > CORE_SCHEMA_VERSION:
        raise FutureSchemaVersion(
            f"core schema version {core_version} is newer than supported "
            f"version {CORE_SCHEMA_VERSION}"
        )

    if core_version == 0:
        if legacy_version >= 7:
            _validate_core_shape(conn)
            conn.execute(
                "INSERT INTO core_schema_meta(version, applied_at) "
                "VALUES(?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (CORE_SCHEMA_VERSION,),
            )
        elif legacy_version > 0:
            raise MigrationError(
                "legacy combined database is too old for direct Core-v1 adoption; "
                "upgrade it with initialize_database() first"
            )
        else:
            _apply_migration(
                conn,
                CORE_SCHEMA_VERSION,
                _migration_text(CORE_SCHEMA_VERSION, CORE_MIGRATION_PACKAGE),
                "core_schema_meta",
            )

    final = current_core_schema_version(conn)
    if final != CORE_SCHEMA_VERSION:
        raise MigrationError(
            f"core schema migration incomplete: expected {CORE_SCHEMA_VERSION}, got {final}"
        )
    _validate_core_shape(conn)


def initialize_database(conn: sqlite3.Connection) -> None:
    """Bring a historical combined Production Runtime database to schema 11.

    This function preserves the original combined schema lineage for existing
    deployments. A new split Core database is intentionally not promoted through
    this legacy migrator; extensions must initialize their own schema explicitly.
    """
    legacy_version = _existing_legacy_schema_version(conn)
    core_version = current_core_schema_version(conn) if _table_exists(
        conn, "core_schema_meta"
    ) else 0
    if legacy_version == 0 and core_version > 0:
        raise MigrationError(
            "split Core database cannot be promoted through the legacy combined "
            "migrator; initialize required extensions explicitly"
        )

    _ensure_schema_meta(conn)
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
