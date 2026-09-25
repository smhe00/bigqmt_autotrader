from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from bigqmt_autotrader.qmt import host as host_module
from bigqmt_autotrader.qmt.host import _resolve_spool_instance, build_parser
from bigqmt_autotrader.qmt.instances import QmtInstanceError, discover_instances, load_instance
from bigqmt_autotrader.qmt.protocol import QmtEvent, encode_transport_frame
from bigqmt_autotrader.qmt.receiver import QmtIngressBuffer, QmtIngressIdentityError


FINGERPRINT = "sha256:" + "a" * 64
SHANGHAI_TZ = timezone(timedelta(hours=8))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_ready_event(root: Path, *, raw_override: bytes | None = None) -> tuple[Path, Path, Path]:
    ready_path = root / "inbox" / "ready.json"
    source_raw = ready_path.read_bytes()
    event = QmtEvent.from_mapping(json.loads(source_raw)["event"])
    ready_path.unlink()
    raw = source_raw if raw_override is None else raw_override
    raw_line = raw if raw.endswith(b"\n") else raw + b"\n"
    day = datetime.fromtimestamp(event.timestamp_ms / 1000.0, tz=SHANGHAI_TZ).date().isoformat()
    archive_dir = root / "archive"
    checkpoint_dir = root / "checkpoints"
    archive_dir.mkdir()
    checkpoint_dir.mkdir()
    archive_path = archive_dir / f"{day}_events.jsonl.gz"
    with open(archive_path, "wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as zipped:
            zipped.write(raw_line)
    archive_hash = _sha256(archive_path)
    manifest = {
        "archive_format_version": "1",
        "trading_day": day,
        "account_fingerprint": FINGERPRINT,
        "event_count": 1,
        "first_timestamp_ms": event.timestamp_ms,
        "last_timestamp_ms": event.timestamp_ms,
        "archive_filename": archive_path.name,
        "archive_sha256": archive_hash,
        "event_stream_sha256": hashlib.sha256(raw_line).hexdigest(),
    }
    manifest_path = archive_dir / f"{day}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    checkpoint = {
        "status": "COMMITTED",
        "trading_day": day,
        "archive_filename": archive_path.name,
        "archive_sha256": archive_hash,
        "manifest_filename": manifest_path.name,
        "manifest_sha256": _sha256(manifest_path),
        "event_count": 1,
    }
    checkpoint_path = checkpoint_dir / f"{day}.json"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    return archive_path, manifest_path, checkpoint_path


def _rewrite_archive_metadata(
    archive_path: Path,
    manifest_path: Path,
    checkpoint_path: Path,
    *,
    manifest_updates: dict[str, object] | None = None,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["archive_sha256"] = _sha256(archive_path)
    if manifest_updates:
        manifest.update(manifest_updates)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["archive_sha256"] = _sha256(archive_path)
    checkpoint["manifest_sha256"] = _sha256(manifest_path)
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")


def _write_instance(base: Path, instance_id: str = "terminal_01") -> Path:
    root = base / instance_id
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    manifest = {
        "manifest_version": "1",
        "terminal_instance_id": instance_id,
        "protocol_version": "0.2",
        "transport_version": "1",
        "bridge_build": "p4-shadow-command-spool-5",
        "session_id": "session-01",
        "account_fingerprint": FINGERPRINT,
        "account_type": "STOCK",
        "created_ms": 1_700_000_000_000,
        "execution_mode": "SHADOW",
        "trading_enabled": False,
        "live_submit": False,
        "live_cancel": False,
    }
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")
    event = {
        "protocol_version": "0.2",
        "terminal_instance_id": instance_id,
        "session_id": "session-01",
        "sequence": 1,
        "timestamp_ms": 1_700_000_000_001,
        "event_type": "bridge_ready",
        "source": "init",
        "account_fingerprint": FINGERPRINT,
        "account_type": "STOCK",
        "payload": {
            "capabilities": {
                "bridge_build": "p4-shadow-command-spool-5",
                "execution_mode": "SHADOW",
                "trading_enabled": False,
                "live_submit": False,
                "live_cancel": False,
                "spool_instance_id": instance_id,
            }
        },
    }
    (inbox / "ready.json").write_bytes(encode_transport_frame(event))
    return root


def _write_simulation_instance(base: Path, instance_id: str = "sim_01") -> Path:
    root = base / instance_id
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    safety = {
        "execution_mode": "SIMULATION_CALIBRATION",
        "trading_enabled": True,
        "live_submit": True,
        "live_cancel": True,
        "simulation_only": True,
        "authorized_account_fingerprint": FINGERPRINT,
        "max_order_quantity": 100,
        "max_submit_calls_per_session": 2000,
        "max_cancel_calls_per_session": 2000,
    }
    manifest = {
        "manifest_version": "1",
        "terminal_instance_id": instance_id,
        "protocol_version": "0.2",
        "transport_version": "1",
        "bridge_build": "p5-simulation-calibration-2",
        "session_id": "sim-session-01",
        "account_fingerprint": FINGERPRINT,
        "account_type": "STOCK",
        "created_ms": 1_700_000_000_000,
        **safety,
    }
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")
    event = {
        "protocol_version": "0.2",
        "terminal_instance_id": instance_id,
        "session_id": "sim-session-01",
        "sequence": 1,
        "timestamp_ms": 1_700_000_000_001,
        "event_type": "bridge_ready",
        "source": "init",
        "account_fingerprint": FINGERPRINT,
        "account_type": "STOCK",
        "payload": {
            "capabilities": {
                "bridge_build": "p5-simulation-calibration-2",
                "spool_instance_id": instance_id,
                **safety,
            }
        },
    }
    (inbox / "ready.json").write_bytes(encode_transport_frame(event))
    return root


def _write_live_canary_instance(base: Path, instance_id: str = "guojin") -> Path:
    root = base / instance_id
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    safety = {
        "execution_mode": "LIVE_CANARY",
        "trading_enabled": True,
        "live_submit": True,
        "live_cancel": True,
        "simulation_only": False,
        "authorized_account_fingerprint": FINGERPRINT,
        "max_order_quantity": 100,
        "max_submit_calls_per_session": 1,
        "max_cancel_calls_per_session": 1,
    }
    manifest = {
        "manifest_version": "1",
        "terminal_instance_id": instance_id,
        "protocol_version": "0.2",
        "transport_version": "1",
        "bridge_build": "p6-guojin-live-canary-3",
        "session_id": "live-session-01",
        "account_fingerprint": FINGERPRINT,
        "account_type": "STOCK",
        "created_ms": 1_700_000_000_000,
        **safety,
    }
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")
    event = {
        "protocol_version": "0.2",
        "terminal_instance_id": instance_id,
        "session_id": "live-session-01",
        "sequence": 1,
        "timestamp_ms": 1_700_000_000_001,
        "event_type": "bridge_ready",
        "source": "init",
        "account_fingerprint": FINGERPRINT,
        "account_type": "STOCK",
        "payload": {"capabilities": {"bridge_build": "p6-guojin-live-canary-3",
                                      "spool_instance_id": instance_id, **safety}},
    }
    (inbox / "ready.json").write_bytes(encode_transport_frame(event))
    return root


def test_discovers_only_manifest_and_bridge_ready_validated_children(tmp_path: Path) -> None:
    _write_instance(tmp_path, "terminal_01")
    for legacy_name in ("archive", "commands", "processed"):
        (tmp_path / legacy_name).mkdir()

    instances = discover_instances(tmp_path)

    assert [item.instance_id for item in instances] == ["terminal_01"]
    assert instances[0].account_fingerprint == FINGERPRINT
    assert instances[0].root == tmp_path / "terminal_01"


def test_manifest_directory_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    manifest = json.loads((root / "instance.json").read_text(encoding="utf-8"))
    manifest["terminal_instance_id"] = "terminal_02"
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(QmtInstanceError, match="terminal_instance_id"):
        load_instance(tmp_path, "terminal_01")
    assert discover_instances(tmp_path) == ()


def test_bridge_ready_session_and_instance_must_match_manifest(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    manifest = json.loads((root / "instance.json").read_text(encoding="utf-8"))
    manifest["session_id"] = "other-session"
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(QmtInstanceError, match="bridge_ready"):
        load_instance(tmp_path, "terminal_01")


def test_current_session_bridge_ready_is_loaded_from_committed_archive(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    _archive_ready_event(root)

    instance = load_instance(tmp_path, "terminal_01")

    assert instance.session_id == "session-01"


def test_same_timestamp_archived_higher_sequence_wins_over_loose_ready(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    ready_path = root / "inbox" / "ready.json"
    event = dict(json.loads(ready_path.read_text(encoding="utf-8"))["event"])

    archived = dict(event)
    archived["sequence"] = 2
    _archive_ready_event(root, raw_override=encode_transport_frame(archived))

    loose = dict(event)
    loose["session_id"] = "loose-session"
    loose["sequence"] = 1
    (root / "inbox" / "loose-ready.json").write_bytes(encode_transport_frame(loose))

    instance = load_instance(tmp_path, "terminal_01")

    assert instance.session_id == "session-01"


def test_same_timestamp_loose_higher_sequence_wins_over_archived_ready(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    ready_path = root / "inbox" / "ready.json"
    event = dict(json.loads(ready_path.read_text(encoding="utf-8"))["event"])

    archived = dict(event)
    archived["session_id"] = "archived-session"
    archived["sequence"] = 1
    _archive_ready_event(root, raw_override=encode_transport_frame(archived))

    loose = dict(event)
    loose["sequence"] = 2
    (root / "inbox" / "loose-ready.json").write_bytes(encode_transport_frame(loose))

    instance = load_instance(tmp_path, "terminal_01")

    assert instance.session_id == "session-01"


def test_same_timestamp_and_sequence_uses_session_id_tiebreak_across_archive(
    tmp_path: Path,
) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    ready_path = root / "inbox" / "ready.json"
    event = dict(json.loads(ready_path.read_text(encoding="utf-8"))["event"])

    manifest_path = root / "instance.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["session_id"] = "session-z"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    archived = dict(event)
    archived["session_id"] = "session-z"
    _archive_ready_event(root, raw_override=encode_transport_frame(archived))

    loose = dict(event)
    loose["session_id"] = "session-a"
    (root / "inbox" / "loose-ready.json").write_bytes(encode_transport_frame(loose))

    instance = load_instance(tmp_path, "terminal_01")

    assert instance.session_id == "session-z"


def test_newer_loose_bridge_ready_wins_over_archived_current_session(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    _archive_ready_event(root)
    newer = {
        "protocol_version": "0.2",
        "terminal_instance_id": "terminal_01",
        "session_id": "newer-session",
        "sequence": 1,
        "timestamp_ms": 1_700_000_000_101,
        "event_type": "bridge_ready",
        "source": "init",
        "account_fingerprint": FINGERPRINT,
        "account_type": "STOCK",
        "payload": {"capabilities": {}},
    }
    (root / "inbox" / "newer-ready.json").write_bytes(encode_transport_frame(newer))

    with pytest.raises(QmtInstanceError, match="latest bridge_ready session mismatch"):
        load_instance(tmp_path, "terminal_01")


def test_corrupt_committed_readiness_archive_fails_closed(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    archive_path, _manifest_path, _checkpoint_path = _archive_ready_event(root)
    archive_path.write_bytes(b"not-a-gzip")

    with pytest.raises(QmtInstanceError, match="archive hash mismatch"):
        load_instance(tmp_path, "terminal_01")


def test_malformed_archived_readiness_frame_fails_closed(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    archive_path, manifest_path, checkpoint_path = _archive_ready_event(
        root,
        raw_override=b'not-json\n',
    )
    _rewrite_archive_metadata(archive_path, manifest_path, checkpoint_path)

    with pytest.raises(QmtInstanceError, match="archive payload is invalid"):
        load_instance(tmp_path, "terminal_01")


def test_archive_manifest_pair_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    archive_path, manifest_path, checkpoint_path = _archive_ready_event(root)
    _rewrite_archive_metadata(
        archive_path,
        manifest_path,
        checkpoint_path,
        manifest_updates={"archive_filename": "other_events.jsonl.gz"},
    )

    with pytest.raises(QmtInstanceError, match="manifest/checkpoint mismatch"):
        load_instance(tmp_path, "terminal_01")


def test_ingress_rejects_other_terminal_instance() -> None:
    ingress = QmtIngressBuffer(
        expected_account_fingerprint=FINGERPRINT,
        expected_terminal_instance_id="terminal_01",
    )
    event = QmtEvent.from_mapping(
        {
            "protocol_version": "0.2",
            "terminal_instance_id": "terminal_02",
            "session_id": "session-01",
            "sequence": 1,
            "timestamp_ms": 1_700_000_000_001,
            "event_type": "bridge_ready",
            "source": "init",
            "account_fingerprint": FINGERPRINT,
            "account_type": "STOCK",
            "payload": {},
        }
    )

    with pytest.raises(QmtIngressIdentityError, match="terminal_instance_id"):
        ingress.ingest(event)


def test_host_defaults_to_broker_neutral_spool_discovery() -> None:
    args = build_parser().parse_args([])
    assert args.instance_id is None
    assert args.spool_base == r"D:\BigQMTData\spool"
    assert args.allow_simulation_mutation is False
    assert args.allow_live_canary is False
    host_source = (Path(__file__).resolve().parents[2] / "src" / "bigqmt_autotrader" / "qmt" / "host.py").read_text(
        encoding="utf-8"
    )
    assert "galaxy" not in host_source.lower()
    assert "allow-live-canary" in host_source
    assert "guojin_sim_oms_authorized" in host_source


def test_simulation_instance_requires_explicit_host_authority(tmp_path: Path) -> None:
    _write_simulation_instance(tmp_path)

    with pytest.raises(QmtInstanceError, match="not authorized"):
        load_instance(tmp_path, "sim_01")
    assert discover_instances(tmp_path) == ()

    instance = load_instance(tmp_path, "sim_01", allow_simulation_mutation=True)
    assert instance.execution_mode == "SIMULATION_CALIBRATION"
    assert instance.simulation_only is True
    assert instance.live_submit is True
    assert instance.live_cancel is True
    assert [item.instance_id for item in discover_instances(
        tmp_path, allow_simulation_mutation=True
    )] == ["sim_01"]


def test_simulation_instance_rejects_unpinned_account(tmp_path: Path) -> None:
    root = _write_simulation_instance(tmp_path)
    manifest = json.loads((root / "instance.json").read_text(encoding="utf-8"))
    manifest["authorized_account_fingerprint"] = "sha256:" + "b" * 64
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(QmtInstanceError, match="fingerprint is not pinned"):
        load_instance(tmp_path, "sim_01", allow_simulation_mutation=True)


def test_live_canary_requires_separate_explicit_host_authority(tmp_path: Path) -> None:
    _write_live_canary_instance(tmp_path)
    with pytest.raises(QmtInstanceError, match="not authorized"):
        load_instance(tmp_path, "guojin")
    with pytest.raises(QmtInstanceError, match="not authorized"):
        load_instance(tmp_path, "guojin", allow_simulation_mutation=True)

    instance = load_instance(tmp_path, "guojin", allow_live_canary=True)
    assert instance.execution_mode == "LIVE_CANARY"
    assert instance.simulation_only is False
    assert instance.account_fingerprint == FINGERPRINT


def test_live_canary_rejects_submit_fuse_above_pin(tmp_path: Path) -> None:
    root = _write_live_canary_instance(tmp_path)
    manifest = json.loads((root / "instance.json").read_text(encoding="utf-8"))
    manifest["max_submit_calls_per_session"] = 2
    (root / "instance.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(QmtInstanceError, match="max_submit_calls_per_session"):
        load_instance(tmp_path, "guojin", allow_live_canary=True)


def test_host_resolves_instance_id_only_from_discovered_manifest(tmp_path: Path) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    args = build_parser().parse_args(
        ["--spool-base", str(tmp_path), "--instance-id", "terminal_01"]
    )

    instance = _resolve_spool_instance(args)

    assert instance.instance_id == "terminal_01"
    assert instance.root == root


def test_host_no_argument_selection_comes_from_discovered_children(
    tmp_path: Path, monkeypatch
) -> None:
    _write_instance(tmp_path, "terminal_01")
    _write_instance(tmp_path, "terminal_02")
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")
    args = build_parser().parse_args(["--spool-base", str(tmp_path)])

    instance = _resolve_spool_instance(args)

    assert instance.instance_id == "terminal_02"


def test_host_no_argument_waits_until_qmt_manifest_exists(tmp_path: Path, monkeypatch) -> None:
    root = _write_instance(tmp_path, "terminal_01")
    instance = load_instance(tmp_path, "terminal_01")
    discoveries = iter([(), (instance,)])
    monkeypatch.setattr(
        host_module,
        "discover_instances",
        lambda _base, **_kwargs: next(discoveries),
    )
    monkeypatch.setattr(host_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(host_module, "_choose_instance", lambda choices: choices[0])
    args = build_parser().parse_args(["--spool-base", str(tmp_path)])

    selected = _resolve_spool_instance(args)

    assert selected.instance_id == "terminal_01"
    assert selected.root == root
