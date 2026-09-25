from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from bigqmt_autotrader.qmt import live_canary_probe as probe
from bigqmt_autotrader.qmt.commands import (
    MAX_COMMAND_FRAME_BYTES,
    QmtCommandSpool,
)
from bigqmt_autotrader.qmt.instances import QmtInstanceError, load_instance
from bigqmt_autotrader.qmt.protocol import encode_transport_frame

ROOT = Path(__file__).resolve().parents[2]
FINGERPRINT = "sha256:" + "a" * 64
SESSION = "live-session-7"
EXPIRES_MS = 1_900_000_000_000  # far in the future relative to any test run


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location(
        "live_canary_runtime_preflight", ROOT / "tools" / "live_canary_runtime_preflight.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


preflight = _load_preflight_module()


def _write_instance(
    base: Path,
    *,
    build: str = probe.BRIDGE_BUILD,
    fuse: int = 1,
    quantity: int = 100,
    session: str = SESSION,
    with_ready: bool = True,
) -> Path:
    root = base / "guojin"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    safety = {
        "execution_mode": "LIVE_CANARY",
        "trading_enabled": True,
        "live_submit": True,
        "live_cancel": True,
        "simulation_only": False,
        "authorized_account_fingerprint": FINGERPRINT,
        "max_order_quantity": quantity,
        "max_submit_calls_per_session": fuse,
        "max_cancel_calls_per_session": fuse,
    }
    manifest = {
        "manifest_version": "1",
        "terminal_instance_id": "guojin",
        "protocol_version": "0.2",
        "transport_version": "1",
        "bridge_build": build,
        "session_id": session,
        "account_fingerprint": FINGERPRINT,
        "account_type": "STOCK",
        "created_ms": 1_700_000_000_000,
        **safety,
    }
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")
    if with_ready:
        event = {
            "protocol_version": "0.2",
            "terminal_instance_id": "guojin",
            "session_id": session,
            "sequence": 1,
            "timestamp_ms": 1_700_000_000_001,
            "event_type": "bridge_ready",
            "source": "init",
            "account_fingerprint": FINGERPRINT,
            "account_type": "STOCK",
            "payload": {
                "capabilities": {"bridge_build": build, "spool_instance_id": "guojin", **safety}
            },
        }
        (inbox / "ready.json").write_bytes(encode_transport_frame(event))
    for subdir in (
        "commands/inbox",
        "commands/claimed",
        "commands/processed",
        "commands/unknown",
        "archive",
        "checkpoints",
        "conflicts",
        "quarantine",
    ):
        (root / subdir).mkdir(parents=True, exist_ok=True)
    return root


def _publish_command(
    instance_root: Path,
    *,
    kind: str,
    session: str | None,
    target_dir: str = "inbox",
    live_canary: bool = True,
) -> Path:
    """Publish a production-path command frame and move it to ``target_dir``."""
    spool = QmtCommandSpool(instance_root)
    if kind == "submit":
        command = spool.publish_submit(
            account_fingerprint=FINGERPRINT,
            client_order_id="preflight-oid-1",
            symbol=probe.AUTHORIZED_SYMBOL,
            side="BUY",
            quantity=100,
            limit_price="1.00",
            expires_ms=EXPIRES_MS,
            live_canary=live_canary,
            expected_qmt_session_id=session,
        )
    elif kind == "cancel":
        command = spool.publish_cancel(
            account_fingerprint=FINGERPRINT,
            client_order_id="preflight-oid-1",
            broker_order_id="BR-1",
            expires_ms=EXPIRES_MS,
            live_canary=live_canary,
            expected_qmt_session_id=session,
        )
    else:
        command = spool.publish_snapshot_request(
            account_fingerprint=FINGERPRINT,
            expires_ms=EXPIRES_MS,
        )
    source = spool.inbox / (command.command_id + ".json")
    if target_dir != "inbox":
        source.rename(spool.commands_root / target_dir / source.name)
    return source


def _host_accepted_fuse(base: Path) -> int:
    """Return the fuse value the current Host pin accepts (schema value first)."""
    schema_pins = preflight.schema_live_canary_pins()
    for index, fuse in enumerate((schema_pins["max_submit_calls_per_session"], 2)):
        root = _write_instance(base / f"probe{index}", fuse=fuse)
        try:
            load_instance(root.parent, "guojin", allow_live_canary=True)
        except QmtInstanceError:
            continue
        return fuse
    raise AssertionError("Host rejects every candidate fuse value")


@pytest.fixture()
def patched_static(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch repository-static checks and the trading window for spool-only tests."""
    monkeypatch.setattr(
        preflight,
        "generator_sync_check",
        lambda: preflight.Check("generator_sync", True, "patched"),
    )
    monkeypatch.setattr(
        preflight,
        "artifact_constants_check",
        lambda: preflight.Check("artifact_constants", True, "patched"),
    )
    monkeypatch.setattr(
        preflight,
        "authority_pin_consistency_check",
        lambda: preflight.Check("authority_pin_consistency", True, "patched"),
    )
    monkeypatch.setattr(probe, "_live_canary_submit_window_open", lambda: True)


# ---------------------------------------------------------------------------
# schema single source


def test_schema_pins_are_the_build7_authority() -> None:
    assert preflight.schema_live_canary_pins() == {
        "max_order_quantity": 100,
        "max_submit_calls_per_session": 1,
        "max_cancel_calls_per_session": 1,
    }


# ---------------------------------------------------------------------------
# static repository checks (real)


def test_generator_sync_check_passes() -> None:
    check = preflight.generator_sync_check()
    assert check.passed, check.detail


def test_artifact_constants_check_passes() -> None:
    check = preflight.artifact_constants_check()
    assert check.passed, check.detail


def test_authority_pin_consistency_check_is_truthful() -> None:
    """The check must report exactly whether the Host accepts schema pins."""
    import tempfile

    check = preflight.authority_pin_consistency_check()
    with tempfile.TemporaryDirectory(prefix="bigqmt-preflight-truth-") as tmp:
        preflight._fabricate_schema_blessed_instance(Path(tmp))
        try:
            load_instance(tmp, "guojin", allow_live_canary=True)
            host_accepts = True
        except QmtInstanceError:
            host_accepts = False
    assert check.passed is host_accepts, check.detail


# ---------------------------------------------------------------------------
# runtime checks against fabricated spools


def test_go_on_clean_build7_instance(tmp_path: Path, patched_static: None) -> None:
    """Full GO requires the Host pin to match the schema pins (T020 alignment)."""
    if not preflight.authority_pin_consistency_check().passed:
        pytest.skip("Host LIVE_CANARY pin diverges from schema pins; GO blocked until aligned")
    _write_instance(tmp_path, fuse=1)
    checks = preflight.runtime_checks(tmp_path, "guojin")
    failed = [check for check in checks if not check.passed]
    assert failed == [], failed
    assert preflight._print_report(checks, as_json=False) is True


@pytest.mark.parametrize(
    ("subdir", "kind"),
    [
        ("inbox", "submit"),
        ("claimed", "submit"),
        ("claimed", "cancel"),
        ("processed", "submit"),
        ("processed", "cancel"),
        ("unknown", "submit"),
        ("unknown", "cancel"),
    ],
)
def test_real_frame_mutation_consumes_current_session_fuse(
    tmp_path: Path, patched_static: None, subdir: str, kind: str
) -> None:
    """Production-path command frames must be recognized as fuse consumption."""
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    _publish_command(tmp_path / "guojin", kind=kind, session=SESSION, target_dir=subdir)
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["fuse_unused"].passed is False, by_name["fuse_unused"].detail
    assert kind.upper() in by_name["fuse_unused"].detail


def test_foreign_session_frame_does_not_consume_fuse(tmp_path: Path, patched_static: None) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    _publish_command(
        tmp_path / "guojin", kind="submit", session="another-session", target_dir="processed"
    )
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["fuse_unused"].passed is True, by_name["fuse_unused"].detail


def test_snapshot_request_does_not_consume_fuse(tmp_path: Path, patched_static: None) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    _publish_command(
        tmp_path / "guojin", kind="snapshot", session=None, target_dir="processed"
    )
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["fuse_unused"].passed is True, by_name["fuse_unused"].detail


def test_mutation_frame_without_session_binding_fails_closed(
    tmp_path: Path, patched_static: None
) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    _publish_command(
        tmp_path / "guojin", kind="submit", session=None, live_canary=False, target_dir="processed"
    )
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["fuse_unused"].passed is False
    assert "fail-closed" in by_name["fuse_unused"].detail


def test_malformed_frame_fails_closed(tmp_path: Path, patched_static: None) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    (tmp_path / "guojin" / "commands" / "processed" / "broken.json").write_bytes(b"not-json")
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["fuse_unused"].passed is False
    assert "fail-closed" in by_name["fuse_unused"].detail


def test_contract_invalid_frame_fails_closed(tmp_path: Path, patched_static: None) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    (tmp_path / "guojin" / "commands" / "claimed" / "wrong.json").write_bytes(
        json.dumps({"command_type": "SUBMIT_LIMIT", "expected_qmt_session_id": SESSION}).encode()
    )
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["fuse_unused"].passed is False
    assert "fail-closed" in by_name["fuse_unused"].detail


def test_oversized_frame_fails_closed(tmp_path: Path, patched_static: None) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    (tmp_path / "guojin" / "commands" / "processed" / "big.json").write_bytes(
        b"0" * (MAX_COMMAND_FRAME_BYTES + 1)
    )
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["fuse_unused"].passed is False
    assert "oversized" in by_name["fuse_unused"].detail


def test_old_flat_json_fixture_is_not_mistaken_for_consumed(
    tmp_path: Path, patched_static: None
) -> None:
    """A flat legacy dict (contract-invalid as a frame) must fail closed, not pass."""
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    (tmp_path / "guojin" / "commands" / "processed" / "cmd-1.json").write_text(
        json.dumps(
            {"command_type": "SUBMIT_LIMIT", "expected_qmt_session_id": SESSION}
        ),
        encoding="utf-8",
    )
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["fuse_unused"].passed is False
    assert "fail-closed" in by_name["fuse_unused"].detail


def test_unknown_leftover_is_no_go(tmp_path: Path, patched_static: None) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    (tmp_path / "guojin" / "commands" / "unknown" / "u1.json").write_text("{}", encoding="utf-8")
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["no_unknown"].passed is False


def test_quarantine_and_conflicts_are_no_go(tmp_path: Path, patched_static: None) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    (tmp_path / "guojin" / "quarantine" / "q1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "guojin" / "conflicts" / "c1.json").write_text("{}", encoding="utf-8")
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["clean_evidence"].passed is False
    assert "quarantine" in by_name["clean_evidence"].detail
    assert "conflicts" in by_name["clean_evidence"].detail


def test_closed_window_is_no_go(tmp_path: Path, patched_static: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "_live_canary_submit_window_open", lambda: False)
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path))
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["window_open"].passed is False


def test_missing_bridge_ready_is_no_go(tmp_path: Path, patched_static: None) -> None:
    _write_instance(tmp_path, fuse=_host_accepted_fuse(tmp_path), with_ready=False)
    checks = preflight.runtime_checks(tmp_path, "guojin")
    by_name = {check.name: check for check in checks}
    assert by_name["instance_load"].passed is False
    downstream = {name for name, check in by_name.items() if "skipped" in check.detail}
    assert {"build_fresh", "manifest_pins", "fuse_unused"} <= downstream


def test_main_end_to_end_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(probe, "_live_canary_submit_window_open", lambda: True)
    _write_instance(tmp_path, fuse=1)
    code = preflight.main(["--spool-root", str(tmp_path), "--instance", "guojin", "--json"])
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    consistent = preflight.authority_pin_consistency_check().passed
    expected_verdict = "GO" if consistent else "NO-GO"
    assert payload["verdict"] == expected_verdict
    assert (code == 0) is (expected_verdict == "GO")
    names = {check["name"] for check in payload["checks"]}
    assert {"generator_sync", "artifact_constants", "authority_pin_consistency", "instance_load"} <= names
