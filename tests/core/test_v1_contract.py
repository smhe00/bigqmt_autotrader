import dataclasses
import json
from pathlib import Path

import bigqmt_autotrader.core as core
from bigqmt_autotrader.domain import OrderIntent, OrderStatus
from bigqmt_autotrader.oms import connect_database, current_core_schema_version, initialize_core_database


ROOT = Path(__file__).resolve().parents[2]


def _contract(name: str):
    return json.loads((ROOT / "contracts" / "core" / "v1" / name).read_text(encoding="utf-8"))


def test_core_public_api_v1_is_frozen():
    contract = _contract("public_api.json")
    assert list(core.__all__) == contract["exports"]
    assert core.CORE_SCHEMA_VERSION == 1
    assert [field.name for field in dataclasses.fields(OrderIntent)] == contract["order_intent_fields"]
    assert [status.value for status in OrderStatus] == contract["order_status_values"]
    for method in contract["execution_core_methods"]:
        assert callable(getattr(core.ExecutionCore, method))


def test_core_schema_v1_matches_snapshot(tmp_path):
    contract = _contract("schema.json")
    conn = connect_database(tmp_path / "core-contract.sqlite3")
    try:
        initialize_core_database(conn)
        assert current_core_schema_version(conn) == contract["core_schema_version"]
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for prefix in contract["forbidden_table_prefixes"]:
            assert not any(name.startswith(prefix) for name in tables)
        expected_tables = set(contract["tables"]) | {"core_schema_meta"}
        assert tables == expected_tables
        for table, expected_columns in contract["tables"].items():
            actual = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
            assert actual == expected_columns
    finally:
        conn.close()
