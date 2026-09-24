from __future__ import annotations

import sqlite3
from importlib import resources

from bigqmt_autotrader.oms.db import MigrationError, initialize_core_database


QMT_SCHEMA_VERSION = 1
QMT_MIGRATION_PACKAGE = "bigqmt_autotrader.qmt.migrations"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS qmt_schema_meta (
               version INTEGER PRIMARY KEY,
               applied_at TEXT NOT NULL
           )"""
    )


def current_qmt_schema_version(conn: sqlite3.Connection) -> int:
    _ensure_meta(conn)
    row = conn.execute("SELECT MAX(version) AS version FROM qmt_schema_meta").fetchone()
    return 0 if row is None or row["version"] is None else int(row["version"])


def _validate_qmt_shape(conn: sqlite3.Connection) -> None:
    required = {
        "qmt_command_results",
        "qmt_durable_command_identities",
        "qmt_execution_dispatches",
    }
    present = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IS NOT NULL"
        )
    }
    missing = sorted(required - present)
    if missing:
        raise MigrationError("QMT extension schema missing tables: " + ", ".join(missing))


def initialize_qmt_database(conn: sqlite3.Connection) -> None:
    initialize_core_database(conn)
    _ensure_meta(conn)
    version = current_qmt_schema_version(conn)
    if version > QMT_SCHEMA_VERSION:
        raise MigrationError(
            f"QMT schema version {version} is newer than supported {QMT_SCHEMA_VERSION}"
        )
    if version == 0:
        qmt_tables = {
            name for name in (
                "qmt_command_results",
                "qmt_durable_command_identities",
                "qmt_execution_dispatches",
            ) if _table_exists(conn, name)
        }
        if qmt_tables:
            if len(qmt_tables) != 3:
                raise MigrationError("partial historical QMT schema detected")
            _validate_qmt_shape(conn)
            conn.execute(
                "INSERT INTO qmt_schema_meta(version, applied_at) "
                "VALUES(?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (QMT_SCHEMA_VERSION,),
            )
        else:
            sql = resources.files(QMT_MIGRATION_PACKAGE).joinpath(
                "0001_initial.sql"
            ).read_text(encoding="utf-8")
            script = (
                "BEGIN IMMEDIATE;\n"
                + sql
                + "\nINSERT INTO qmt_schema_meta(version, applied_at) "
                + "VALUES(1, strftime('%Y-%m-%dT%H:%M:%fZ','now'));\n"
                + "COMMIT;\n"
            )
            try:
                conn.executescript(script)
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                raise
    if current_qmt_schema_version(conn) != QMT_SCHEMA_VERSION:
        raise MigrationError("QMT extension schema migration incomplete")
    _validate_qmt_shape(conn)
