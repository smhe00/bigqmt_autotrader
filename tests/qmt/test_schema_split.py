from bigqmt_autotrader.oms import connect_database, current_core_schema_version
from bigqmt_autotrader.qmt.schema import (
    QMT_SCHEMA_VERSION,
    current_qmt_schema_version,
    initialize_qmt_database,
)


def test_qmt_extension_schema_is_separate_from_core(tmp_path):
    conn = connect_database(tmp_path / "qmt.sqlite3")
    try:
        initialize_qmt_database(conn)
        assert current_core_schema_version(conn) == 1
        assert current_qmt_schema_version(conn) == QMT_SCHEMA_VERSION == 1
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IS NOT NULL"
            )
        }
        assert {
            "qmt_command_results",
            "qmt_durable_command_identities",
            "qmt_execution_dispatches",
        } <= tables
        assert "daily_risk_events" not in tables
        assert "runtime_mode_transitions" not in tables
        assert "operations_alert_events" not in tables
    finally:
        conn.close()
