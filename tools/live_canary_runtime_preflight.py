#!/usr/bin/env python3
"""Read-only GO/NO-GO preflight for the P6 Guojin HGT live canary runtime gate.

Run this before loading the live canary build in the QMT terminal. The tool
never writes to the spool and never mutates anything: it only reads repository
sources, the instance manifest, bridge_ready evidence, command spool state and
the live canary probe's trading-window logic.

Checks
------
1. generator_sync      tools/build_qmt_deployments.py --check passes.
2. artifact_constants  generated guojin bridge constants match the Host probe.
3. authority_pin_consistency  the Host accepts a schema-blessed LIVE_CANARY
                       manifest (catches schema/Host pin divergence).
4. instance_load       load_instance(allow_live_canary=True) validates the real
                       manifest, bridge_ready session/instance/account.
5. build_fresh         manifest bridge_build equals the pinned build-7.
6. manifest_pins       manifest fuse/quantity values equal the schema constants.
7. fuse_unused         no SUBMIT_LIMIT/CANCEL_ORDER command exists for the
                       current session in commands/{inbox,claimed,processed,unknown}.
8. no_unknown          commands/unknown is empty (unreconciled UNKNOWN blocks).
9. clean_evidence      events quarantine/ and conflicts/ are empty.
10. window_open        HGT submit window is open (probe logic, same as bridge).

Manual operator checklist (REMINDER only, does not affect the verdict):
- QMT terminal is running and the canary bridge is loaded;
- publisher confirmation string matches AUTHORIZED_CASE_TEXT;
- the single authorized case is 00700.HGT BUY 100 @ 1.00 HKD (fuse 1/1).
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from bigqmt_autotrader.qmt import live_canary_probe as probe
from bigqmt_autotrader.qmt.instances import QmtInstance, QmtInstanceError, load_instance
from bigqmt_autotrader.qmt.protocol import encode_transport_frame

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "bridge" / "v1" / "instance.schema.json"
ARTIFACT_PATH = ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py"
GENERATOR_PATH = ROOT / "tools" / "build_qmt_deployments.py"
DEFAULT_SPOOL_ROOT = r"D:\BigQMTData\spool"
DEFAULT_INSTANCE = "guojin"
MUTATION_COMMAND_TYPES = frozenset({"SUBMIT_LIMIT", "CANCEL_ORDER"})
COMMAND_SCAN_DIRS = ("inbox", "claimed", "processed", "unknown")
MAX_COMMAND_FILE_BYTES = 1 << 20
PIN_KEYS = ("max_order_quantity", "max_submit_calls_per_session", "max_cancel_calls_per_session")


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def schema_live_canary_pins() -> dict[str, int]:
    """Return the LIVE_CANARY fuse/quantity constants from the schema (single source)."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for clause in schema.get("allOf", []):
        trigger = clause.get("if", {}).get("properties", {}).get("execution_mode", {})
        if trigger.get("const") == "LIVE_CANARY":
            props = clause["then"]["properties"]
            return {key: props[key]["const"] for key in PIN_KEYS}
    raise RuntimeError("LIVE_CANARY branch missing from instance schema")


def load_artifact_module() -> object:
    """Import the generated guojin bridge artifact, suppressing its status print."""
    spec = importlib.util.spec_from_file_location("bigqmt_guojin_bridge_artifact", ARTIFACT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module


def generator_sync_check() -> Check:
    proc = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    detail = (proc.stdout.strip() or proc.stderr.strip() or "ok").splitlines()[-1]
    return Check("generator_sync", proc.returncode == 0, detail)


def artifact_constants_check() -> Check:
    module = load_artifact_module()
    expected = [
        ("BRIDGE_BUILD", module.BRIDGE_BUILD, probe.BRIDGE_BUILD),
        ("mutation_symbols", module._LIVE_CANARY_MUTATION_SYMBOLS, (probe.AUTHORIZED_SYMBOL,)),
        ("authorized_side", module._LIVE_CANARY_AUTHORIZED_SIDE, probe.AUTHORIZED_SIDE),
        ("authorized_quantity", module._LIVE_CANARY_AUTHORIZED_QUANTITY, probe.AUTHORIZED_QUANTITY),
        (
            "authorized_limit_price",
            Decimal(str(module._LIVE_CANARY_AUTHORIZED_LIMIT_PRICE)),
            probe.AUTHORIZED_LIMIT_PRICE,
        ),
    ]
    mismatches = [f"{name}: artifact={got!r} probe={want!r}" for name, got, want in expected if got != want]
    if mismatches:
        return Check("artifact_constants", False, "; ".join(mismatches))
    return Check("artifact_constants", True, f"build={module.BRIDGE_BUILD} case={probe.AUTHORIZED_CASE_TEXT}")


def _fabricate_schema_blessed_instance(base: Path) -> Path:
    """Write a minimal LIVE_CANARY instance using schema constants only."""
    pins = schema_live_canary_pins()
    fingerprint = "sha256:" + "0" * 64
    session = "preflight-pin-probe"
    safety = {
        "execution_mode": "LIVE_CANARY",
        "trading_enabled": True,
        "live_submit": True,
        "live_cancel": True,
        "simulation_only": False,
        "authorized_account_fingerprint": fingerprint,
        **pins,
    }
    manifest = {
        "manifest_version": "1",
        "terminal_instance_id": "guojin",
        "protocol_version": "0.2",
        "transport_version": "1",
        "bridge_build": probe.BRIDGE_BUILD,
        "session_id": session,
        "account_fingerprint": fingerprint,
        "account_type": "STOCK",
        "created_ms": 1,
        **safety,
    }
    root = base / "guojin"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")
    event = {
        "protocol_version": "0.2",
        "terminal_instance_id": "guojin",
        "session_id": session,
        "sequence": 1,
        "timestamp_ms": 1,
        "event_type": "bridge_ready",
        "source": "init",
        "account_fingerprint": fingerprint,
        "account_type": "STOCK",
        "payload": {
            "capabilities": {
                "bridge_build": probe.BRIDGE_BUILD,
                "spool_instance_id": "guojin",
                **safety,
            }
        },
    }
    (inbox / "ready.json").write_bytes(encode_transport_frame(event))
    return root


def authority_pin_consistency_check() -> Check:
    """The Host must accept a manifest blessed by the schema's LIVE_CANARY pins.

    A failure here means the Host's LIVE_CANARY pin diverged from the schema
    (e.g. fuse constants), which would reject a gate-conformant manifest at
    load time.
    """
    with tempfile.TemporaryDirectory(prefix="bigqmt-preflight-pin-") as tmp:
        _fabricate_schema_blessed_instance(Path(tmp))
        try:
            load_instance(tmp, "guojin", allow_live_canary=True)
        except QmtInstanceError as exc:
            pins = schema_live_canary_pins()
            return Check(
                "authority_pin_consistency",
                False,
                f"Host rejected schema-blessed manifest (schema pins {pins}): {exc}",
            )
    return Check("authority_pin_consistency", True, "Host accepts schema-blessed LIVE_CANARY manifest")


def instance_load_check(spool_root: Path, instance_id: str) -> tuple[Check, QmtInstance | None]:
    try:
        instance = load_instance(spool_root, instance_id, allow_live_canary=True)
    except QmtInstanceError as exc:
        return Check("instance_load", False, str(exc)), None
    detail = (
        f"session={instance.session_id} build={instance.bridge_build} "
        f"mode={instance.execution_mode} fingerprint_pinned"
    )
    return Check("instance_load", True, detail), instance


def build_fresh_check(instance: QmtInstance | None) -> Check:
    if instance is None:
        return Check("build_fresh", False, "skipped: instance_load failed")
    if instance.bridge_build != probe.BRIDGE_BUILD:
        return Check(
            "build_fresh",
            False,
            f"manifest build={instance.bridge_build} != pinned {probe.BRIDGE_BUILD} "
            "(reload the build-7 artifact in the QMT terminal)",
        )
    return Check("build_fresh", True, f"build={instance.bridge_build}")


def manifest_pins_check(spool_root: Path, instance_id: str, instance: QmtInstance | None) -> Check:
    if instance is None:
        return Check("manifest_pins", False, "skipped: instance_load failed")
    manifest = json.loads((spool_root / instance_id / "instance.json").read_text(encoding="utf-8"))
    pins = schema_live_canary_pins()
    mismatches = [
        f"{key}: manifest={manifest.get(key)!r} schema={expected!r}"
        for key, expected in pins.items()
        if manifest.get(key) != expected
    ]
    if mismatches:
        return Check("manifest_pins", False, "; ".join(mismatches))
    return Check("manifest_pins", True, ", ".join(f"{key}={pins[key]}" for key in PIN_KEYS))


def fuse_unused_check(spool_root: Path, instance_id: str, instance: QmtInstance | None) -> Check:
    if instance is None:
        return Check("fuse_unused", False, "skipped: instance_load failed")
    consumed: list[str] = []
    commands_root = spool_root / instance_id / "commands"
    for subdir in COMMAND_SCAN_DIRS:
        directory = commands_root / subdir
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            if path.stat().st_size > MAX_COMMAND_FILE_BYTES:
                consumed.append(f"{subdir}/{path.name}: oversized, treat as consumed")
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                consumed.append(f"{subdir}/{path.name}: unreadable ({exc})")
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("expected_qmt_session_id") != instance.session_id:
                continue
            if payload.get("command_type") in MUTATION_COMMAND_TYPES:
                consumed.append(f"{subdir}/{path.name}: {payload.get('command_type')}")
    if consumed:
        return Check(
            "fuse_unused",
            False,
            "session fuse consumed (restart does not re-arm it): " + "; ".join(consumed),
        )
    return Check("fuse_unused", True, "no mutation command for the current session")


def no_unknown_check(spool_root: Path, instance_id: str) -> Check:
    unknown = spool_root / instance_id / "commands" / "unknown"
    count = len(list(unknown.glob("*.json"))) if unknown.is_dir() else 0
    if count:
        return Check("no_unknown", False, f"commands/unknown holds {count} unreconciled result(s)")
    return Check("no_unknown", True, "commands/unknown empty")


def clean_evidence_check(spool_root: Path, instance_id: str) -> Check:
    problems: list[str] = []
    for name in ("quarantine", "conflicts"):
        directory = spool_root / instance_id / name
        count = len(list(directory.glob("*"))) if directory.is_dir() else 0
        if count:
            problems.append(f"{name}/ holds {count} unexplained item(s)")
    if problems:
        return Check("clean_evidence", False, "; ".join(problems))
    return Check("clean_evidence", True, "quarantine/ and conflicts/ empty")


def window_open_check() -> Check:
    if probe._live_canary_submit_window_open():
        return Check("window_open", True, "HGT submit window is open")
    return Check("window_open", False, "outside HGT submit window (Mon-Fri 09:30-11:50 / 13:00-15:50 Shanghai)")


def static_checks() -> list[Check]:
    return [generator_sync_check(), artifact_constants_check(), authority_pin_consistency_check()]


def runtime_checks(spool_root: Path, instance_id: str) -> list[Check]:
    load_check, instance = instance_load_check(spool_root, instance_id)
    return [
        load_check,
        build_fresh_check(instance),
        manifest_pins_check(spool_root, instance_id, instance),
        fuse_unused_check(spool_root, instance_id, instance),
        no_unknown_check(spool_root, instance_id),
        clean_evidence_check(spool_root, instance_id),
        window_open_check(),
    ]


MANUAL_REMINDERS = (
    "QMT terminal is running and the canary bridge is loaded",
    "publisher confirmation string matches the authorized case text",
    "single authorized case: 00700.HGT BUY 100 @ 1.00 HKD (submit/cancel fuse 1/1)",
)


def _print_report(checks: list[Check], as_json: bool) -> bool:
    verdict = "GO" if all(check.passed for check in checks) else "NO-GO"
    if as_json:
        print(
            json.dumps(
                {
                    "verdict": verdict,
                    "checks": [
                        {"name": check.name, "passed": check.passed, "detail": check.detail}
                        for check in checks
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return verdict == "GO"
    for check in checks:
        marker = "PASS " if check.passed else "NO-GO"
        print(f"[{marker}] {check.name}: {check.detail}")
    print(f"VERDICT: {verdict}")
    print("Manual checklist (operator, not machine-checked):")
    for item in MANUAL_REMINDERS:
        print(f"  - {item}")
    return verdict == "GO"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spool-root", default=DEFAULT_SPOOL_ROOT, help="QMT spool root directory")
    parser.add_argument("--instance", default=DEFAULT_INSTANCE, help="spool instance id to check")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    spool_root = Path(args.spool_root)
    checks = static_checks() + runtime_checks(spool_root, args.instance)
    go = _print_report(checks, args.json)
    return 0 if go else 1


if __name__ == "__main__":
    raise SystemExit(main())
