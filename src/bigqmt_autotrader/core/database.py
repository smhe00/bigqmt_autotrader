from __future__ import annotations

import sqlite3

from bigqmt_autotrader.oms import (
    SUPPORTED_SCHEMA_VERSION,
    current_schema_version,
)


RUNTIME_SCHEMA_VERSION = SUPPORTED_SCHEMA_VERSION


def database_schema_version(conn: sqlite3.Connection) -> int:
    """Public database-version query without exposing OMS internals."""
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    return current_schema_version(conn)
