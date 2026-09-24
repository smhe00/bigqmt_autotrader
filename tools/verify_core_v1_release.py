#!/usr/bin/env python3
"""Fail closed if the frozen Execution Core v1 contract drifts."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import bigqmt_autotrader.core as core
from bigqmt_autotrader.oms import (
    connect_database,
    current_core_schema_version,
    initialize_core_database,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "core" / "v1"


def _load(name: str):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def _fail(message: str) -> None:
    raise SystemExit("CORE V1 RELEASE GATE FAILED: " + message)


def _verify_public_api() -> None:
    spec = _load("public_api.json")
    if list(core.__all__) != spec["exports"]:
        _fail("public API exports drifted")
    if core.CORE_SCHEMA_VERSION != spec.get("core_schema_version", 1):
        if core.CORE_SCHEMA_VERSION != 1:
            _fail("CORE_SCHEMA_VERSION drifted")
    for method in spec["execution_core_methods"]:
        if not callable(getattr(core.ExecutionCore, method, None)):
            _fail("ExecutionCore method missing: " + method)


def _verify_schema() -> None:
    spec = _load("schema.json")
    with tempfile.TemporaryDirectory() as directory:
        conn = connect_database(Path(directory) / "core.sqlite3")
        try:
            initialize_core_database(conn)
            if current_core_schema_version(conn) != spec["core_schema_version"]:
                _fail("Core schema version drifted")
            tables = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            expected = set(spec["tables"]) | {"core_schema_meta"}
            if tables != expected:
                _fail(
                    "Core table set drifted: expected "
                    + repr(sorted(expected))
                    + ", got "
                    + repr(sorted(tables))
                )
            for prefix in spec["forbidden_table_prefixes"]:
                if any(name.startswith(prefix) for name in tables):
                    _fail("extension table leaked into Core schema: " + prefix)
            for table, columns in spec["tables"].items():
                actual = [
                    str(row["name"])
                    for row in conn.execute(f"PRAGMA table_info({table})")
                ]
                if actual != columns:
                    _fail(f"Core schema columns drifted for {table}")
        finally:
            conn.close()


def _verify_import_isolation() -> None:
    code = r"""
import sys
import bigqmt_autotrader.core
forbidden = (
    "bigqmt_autotrader.drivers",
    "bigqmt_autotrader.qmt",
    "bigqmt_autotrader.risk",
    "bigqmt_autotrader.market_data",
    "bigqmt_autotrader.operations",
    "bigqmt_autotrader.service",
    "bigqmt_autotrader.strategy_api",
    "bigqmt_autotrader.runtime",
    "bigqmt_autotrader.web",
)
loaded = [
    name for name in sys.modules
    if any(name == root or name.startswith(root + ".") for root in forbidden)
]
if loaded:
    raise SystemExit(",".join(sorted(loaded)))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _fail("Core import loads extension modules: " + (result.stderr or result.stdout))


def _verify_formal_contract() -> None:
    spec = _load("formal_models.json")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for item in spec["models"]:
        tla = ROOT / "formal" / (item["module"] + ".tla")
        cfg = ROOT / "formal" / item["config"]
        if not tla.is_file() or not cfg.is_file():
            _fail("missing frozen formal model: " + item["module"])
        if item["module"] + ".tla" not in workflow or item["config"] not in workflow:
            _fail("frozen formal model is no longer executed by CI: " + item["module"])


def _verify_release_manifest() -> None:
    release = _load("release.json")
    if release["release"] != "core-v1.0.0":
        _fail("release identity drifted")
    if release["status"] not in {"RELEASE_CANDIDATE", "FROZEN"}:
        _fail("invalid release status")
    for relative in release["contracts"]:
        if not (ROOT / relative).is_file():
            _fail("release contract missing: " + relative)


def main() -> None:
    _verify_public_api()
    _verify_schema()
    _verify_import_isolation()
    _verify_formal_contract()
    _verify_release_manifest()
    print("CORE V1 RELEASE GATE PASS")
    print("  release: core-v1.0.0")
    print("  schema: Core v1")
    print("  extension imports: isolated")
    print("  formal contract: present in CI")


if __name__ == "__main__":
    main()
