import pytest

from bigqmt_autotrader.oms import (
    FutureSchemaVersion,
    SUPPORTED_SCHEMA_VERSION,
    connect_database,
    current_schema_version,
    initialize_database,
)


def test_fresh_database_migrates_to_supported_version(tmp_path):
    conn = connect_database(tmp_path / "fresh.sqlite3")
    initialize_database(conn)
    assert current_schema_version(conn) == SUPPORTED_SCHEMA_VERSION == 9
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(broker_orders)").fetchall()
    }
    assert "cancel_call_started" in columns
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IS NOT NULL"
        ).fetchall()
    }
    assert "oms_leader" in tables
    assert "broker_evidence_keys" in tables
    assert "broker_evidence_observations" in tables
    assert "qmt_command_results" in tables
    assert "qmt_durable_command_identities" in tables
    assert "daily_risk_events" in tables
    assert "daily_risk_pnl_snapshots" in tables
    evidence_key_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(broker_evidence_keys)")
    }
    assert {"account_fingerprint", "semantic_digest"} <= evidence_key_columns
    observation_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(broker_evidence_observations)")
    }
    assert {
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
    } <= observation_columns


def test_initialize_is_idempotent(tmp_path):
    conn = connect_database(tmp_path / "idem.sqlite3")
    initialize_database(conn)
    initialize_database(conn)
    rows = conn.execute("SELECT version FROM schema_meta ORDER BY version").fetchall()
    assert [row["version"] for row in rows] == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_future_schema_fails_closed(tmp_path):
    conn = connect_database(tmp_path / "future.sqlite3")
    initialize_database(conn)
    conn.execute(
        "INSERT INTO schema_meta(version, applied_at) VALUES(99, 'future')"
    )
    with pytest.raises(FutureSchemaVersion):
        initialize_database(conn)


def test_packaged_migrations_create_foreign_keys_and_indexes(tmp_path):
    conn = connect_database(tmp_path / "shape.sqlite3")
    initialize_database(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    indexes = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IS NOT NULL"
        ).fetchall()
    }
    assert "idx_order_events_key" in indexes
    assert "idx_broker_evidence_order" in indexes
    assert "idx_broker_evidence_fingerprint" in indexes
    assert "idx_qmt_command_results_order" in indexes
    assert "idx_broker_evidence_source_account_event_id" in indexes
    assert "idx_daily_risk_events_account_date" in indexes
    assert "idx_daily_risk_events_strategy_date" in indexes
    assert "idx_daily_risk_pnl_account_date" in indexes
