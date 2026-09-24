from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from .protocol import BRIDGE_PROTOCOL_VERSION, TRANSPORT_VERSION, QmtEvent, decode_transport_frame


INSTANCE_MANIFEST_VERSION = "1"
INSTANCE_MANIFEST_NAME = "instance.json"
MAX_INSTANCE_MANIFEST_BYTES = 16 * 1024
MAX_ARCHIVE_MANIFEST_BYTES = 16 * 1024 * 1024
ARCHIVE_FORMAT_VERSION = "1"
SHANGHAI_TZ = timezone(timedelta(hours=8))
DEFAULT_SPOOL_BASE = Path(r"D:\BigQMTData\spool")
_INSTANCE_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_ACCOUNT_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class QmtInstanceError(ValueError):
    """A spool child cannot be trusted as a QMT terminal instance."""


@dataclass(frozen=True)
class QmtInstance:
    instance_id: str
    root: Path
    session_id: str
    account_fingerprint: str
    account_type: str
    bridge_build: str
    created_ms: int
    execution_mode: str
    trading_enabled: bool
    live_submit: bool
    live_cancel: bool
    simulation_only: bool


def valid_instance_id(value: str) -> bool:
    return bool(_INSTANCE_ID_RE.fullmatch(value))


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise QmtInstanceError("instance directory is not readable") from exc
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QmtInstanceError("instance manifest is not readable") from exc
    if not raw or len(raw) > MAX_INSTANCE_MANIFEST_BYTES:
        raise QmtInstanceError("invalid instance manifest size")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QmtInstanceError("invalid instance manifest JSON") from exc
    if not isinstance(value, dict):
        raise QmtInstanceError("instance manifest must be an object")
    return value


def _latest_bridge_ready(root: Path) -> QmtEvent:
    candidates: list[Path] = []
    for directory_name in ("inbox", "processed"):
        directory = root / directory_name
        if directory.is_dir() and not _is_link_or_reparse(directory):
            candidates.extend(directory.glob("*.json"))
    ready_events: list[QmtEvent] = []
    for path in candidates:
        try:
            event = decode_transport_frame(path.read_bytes())
        except Exception:
            continue
        if event.event_type == "bridge_ready":
            ready_events.append(event)

    best_timestamp = max(
        (event.timestamp_ms for event in ready_events),
        default=-1,
    )
    archive_dir = root / "archive"
    checkpoint_dir = root / "checkpoints"
    if (
        archive_dir.is_dir()
        and checkpoint_dir.is_dir()
        and not _is_link_or_reparse(archive_dir)
        and not _is_link_or_reparse(checkpoint_dir)
    ):
        manifests: list[tuple[int, Path, dict[str, object], Path]] = []
        for checkpoint_path in checkpoint_dir.glob("*.json"):
            manifest_path, archive_path, manifest = _read_committed_archive_metadata(
                archive_dir,
                checkpoint_path,
            )
            last_timestamp_ms = manifest.get("last_timestamp_ms")
            if isinstance(last_timestamp_ms, bool) or not isinstance(last_timestamp_ms, int):
                raise QmtInstanceError("archive manifest timestamp is invalid")
            manifests.append((last_timestamp_ms, archive_path, manifest, manifest_path))

        for last_timestamp_ms, archive_path, manifest, _manifest_path in sorted(
            manifests,
            key=lambda item: item[0],
            reverse=True,
        ):
            if last_timestamp_ms < best_timestamp:
                break
            archived_ready = _read_archive_bridge_ready(archive_path, manifest)
            ready_events.extend(archived_ready)
            if archived_ready:
                best_timestamp = max(
                    best_timestamp,
                    max(event.timestamp_ms for event in archived_ready),
                )
    if not ready_events:
        raise QmtInstanceError("bridge_ready event not found")
    return max(ready_events, key=lambda event: (event.timestamp_ms, event.sequence, event.session_id))


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise QmtInstanceError("committed archive is not readable") from exc
    return digest.hexdigest()


def _read_bounded_json(path: Path, *, limit: int, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QmtInstanceError(f"{label} is not readable") from exc
    if not raw or len(raw) > limit:
        raise QmtInstanceError(f"invalid {label} size")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QmtInstanceError(f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise QmtInstanceError(f"{label} must be an object")
    return value


def _read_committed_archive_metadata(
    archive_dir: Path,
    checkpoint_path: Path,
) -> tuple[Path, Path, dict[str, object]]:
    if _is_link_or_reparse(checkpoint_path):
        raise QmtInstanceError("archive checkpoint must not be a link")
    checkpoint = _read_bounded_json(
        checkpoint_path,
        limit=MAX_INSTANCE_MANIFEST_BYTES,
        label="archive checkpoint",
    )
    if checkpoint.get("status") != "COMMITTED":
        raise QmtInstanceError("archive checkpoint is not committed")
    manifest_name = checkpoint.get("manifest_filename")
    archive_name = checkpoint.get("archive_filename")
    if (
        not isinstance(manifest_name, str)
        or Path(manifest_name).name != manifest_name
        or not isinstance(archive_name, str)
        or Path(archive_name).name != archive_name
    ):
        raise QmtInstanceError("archive checkpoint filename is invalid")
    manifest_path = archive_dir / manifest_name
    archive_path = archive_dir / archive_name
    if _is_link_or_reparse(manifest_path) or _is_link_or_reparse(archive_path):
        raise QmtInstanceError("committed archive files must not be links")
    if _sha256_path(manifest_path) != checkpoint.get("manifest_sha256"):
        raise QmtInstanceError("archive manifest hash mismatch")
    manifest = _read_bounded_json(
        manifest_path,
        limit=MAX_ARCHIVE_MANIFEST_BYTES,
        label="archive manifest",
    )
    if (
        manifest.get("archive_format_version") != ARCHIVE_FORMAT_VERSION
        or manifest.get("archive_filename") != archive_name
        or manifest_path.stem.removesuffix("_manifest")
        != checkpoint_path.stem
        or manifest.get("trading_day") != checkpoint.get("trading_day")
        or manifest.get("event_count") != checkpoint.get("event_count")
    ):
        raise QmtInstanceError("archive manifest/checkpoint mismatch")
    expected_archive_hash = checkpoint.get("archive_sha256")
    if (
        not isinstance(expected_archive_hash, str)
        or manifest.get("archive_sha256") != expected_archive_hash
        or _sha256_path(archive_path) != expected_archive_hash
    ):
        raise QmtInstanceError("archive hash mismatch")
    return manifest_path, archive_path, manifest


def _read_archive_bridge_ready(
    archive_path: Path,
    manifest: dict[str, object],
) -> list[QmtEvent]:
    digest = hashlib.sha256()
    decoded: list[QmtEvent] = []
    try:
        with gzip.open(archive_path, "rb") as handle:
            for raw in handle:
                digest.update(raw if raw.endswith(b"\n") else raw + b"\n")
                decoded.append(decode_transport_frame(raw))
    except Exception as exc:
        raise QmtInstanceError("archive payload is invalid") from exc
    event_count = manifest.get("event_count")
    if (
        isinstance(event_count, bool)
        or not isinstance(event_count, int)
        or len(decoded) != event_count
    ):
        raise QmtInstanceError("archive event count mismatch")
    if digest.hexdigest() != manifest.get("event_stream_sha256"):
        raise QmtInstanceError("archive event stream hash mismatch")
    trading_day = manifest.get("trading_day")
    if not isinstance(trading_day, str):
        raise QmtInstanceError("archive trading day is invalid")
    if any(
        datetime.fromtimestamp(event.timestamp_ms / 1000.0, tz=SHANGHAI_TZ)
        .date()
        .isoformat()
        != trading_day
        for event in decoded
    ):
        raise QmtInstanceError("archive contains a different trading day")
    fingerprints = {event.account_fingerprint for event in decoded}
    if fingerprints != {manifest.get("account_fingerprint")}:
        raise QmtInstanceError("archive account fingerprint mismatch")
    return [event for event in decoded if event.event_type == "bridge_ready"]


def load_instance(
    spool_base: str | os.PathLike[str],
    instance_id: str,
    *,
    allow_simulation_mutation: bool = False,
    allow_live_canary: bool = False,
) -> QmtInstance:
    if not valid_instance_id(instance_id):
        raise QmtInstanceError("invalid instance_id")
    base = Path(spool_base).expanduser().resolve()
    root = base / instance_id
    if not root.is_dir() or _is_link_or_reparse(root):
        raise QmtInstanceError("invalid instance directory")
    manifest = _read_manifest(root / INSTANCE_MANIFEST_NAME)

    required = {
        "manifest_version": INSTANCE_MANIFEST_VERSION,
        "terminal_instance_id": instance_id,
        "protocol_version": BRIDGE_PROTOCOL_VERSION,
        "transport_version": TRANSPORT_VERSION,
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise QmtInstanceError(f"instance manifest mismatch: {key}")

    execution_mode = manifest.get("execution_mode")
    if execution_mode == "SHADOW":
        safety_required = {
            "trading_enabled": False,
            "live_submit": False,
            "live_cancel": False,
        }
    elif execution_mode == "SIMULATION_CALIBRATION" and allow_simulation_mutation:
        safety_required = {
            "trading_enabled": True,
            "live_submit": True,
            "live_cancel": True,
            "simulation_only": True,
            "max_order_quantity": 100,
            "max_submit_calls_per_session": 2000,
            "max_cancel_calls_per_session": 2000,
        }
    elif execution_mode == "LIVE_CANARY" and allow_live_canary:
        safety_required = {
            "trading_enabled": True,
            "live_submit": True,
            "live_cancel": True,
            "simulation_only": False,
            "max_order_quantity": 100,
            "max_submit_calls_per_session": 2,
            "max_cancel_calls_per_session": 2,
        }
    else:
        raise QmtInstanceError("instance execution mode is not authorized")
    for key, expected in safety_required.items():
        if manifest.get(key) != expected:
            raise QmtInstanceError(f"instance manifest mismatch: {key}")

    session_id = manifest.get("session_id")
    fingerprint = manifest.get("account_fingerprint")
    account_type = manifest.get("account_type")
    bridge_build = manifest.get("bridge_build")
    created_ms = manifest.get("created_ms")
    if not isinstance(session_id, str) or not session_id:
        raise QmtInstanceError("invalid instance session_id")
    if not isinstance(fingerprint, str) or not _ACCOUNT_FINGERPRINT_RE.fullmatch(fingerprint):
        raise QmtInstanceError("invalid instance account_fingerprint")
    if not isinstance(account_type, str) or not account_type:
        raise QmtInstanceError("invalid instance account_type")
    if not isinstance(bridge_build, str) or not bridge_build:
        raise QmtInstanceError("invalid instance bridge_build")
    if isinstance(created_ms, bool) or not isinstance(created_ms, int) or created_ms <= 0:
        raise QmtInstanceError("invalid instance created_ms")
    if execution_mode in {"SIMULATION_CALIBRATION", "LIVE_CANARY"}:
        if manifest.get("authorized_account_fingerprint") != fingerprint:
            raise QmtInstanceError("mutation instance account fingerprint is not pinned")

    ready = _latest_bridge_ready(root)
    if ready.session_id != session_id:
        raise QmtInstanceError("latest bridge_ready session mismatch")
    if ready.terminal_instance_id != instance_id:
        raise QmtInstanceError("bridge_ready instance mismatch")
    if ready.account_fingerprint != fingerprint or ready.account_type != account_type:
        raise QmtInstanceError("bridge_ready account mismatch")
    capabilities = ready.payload.get("capabilities")
    if not isinstance(capabilities, dict):
        raise QmtInstanceError("bridge_ready capabilities missing")
    capability_required = {
        "bridge_build": bridge_build,
        "execution_mode": execution_mode,
        **safety_required,
        "spool_instance_id": instance_id,
    }
    if execution_mode in {"SIMULATION_CALIBRATION", "LIVE_CANARY"}:
        capability_required["authorized_account_fingerprint"] = fingerprint
    for key, expected in capability_required.items():
        if capabilities.get(key) != expected:
            raise QmtInstanceError(f"bridge_ready capability mismatch: {key}")

    return QmtInstance(
        instance_id=instance_id,
        root=root,
        session_id=session_id,
        account_fingerprint=fingerprint,
        account_type=account_type,
        bridge_build=bridge_build,
        created_ms=created_ms,
        execution_mode=execution_mode,
        trading_enabled=bool(manifest.get("trading_enabled")),
        live_submit=bool(manifest.get("live_submit")),
        live_cancel=bool(manifest.get("live_cancel")),
        simulation_only=manifest.get("simulation_only") is True,
    )


def discover_instances(
    spool_base: str | os.PathLike[str],
    *,
    allow_simulation_mutation: bool = False,
    allow_live_canary: bool = False,
) -> tuple[QmtInstance, ...]:
    base = Path(spool_base).expanduser().resolve()
    if not base.is_dir() or _is_link_or_reparse(base):
        return ()
    instances: list[QmtInstance] = []
    for child in sorted(base.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or not valid_instance_id(child.name):
            continue
        try:
            instances.append(
                load_instance(
                    base,
                    child.name,
                    allow_simulation_mutation=allow_simulation_mutation,
                    allow_live_canary=allow_live_canary,
                )
            )
        except QmtInstanceError:
            continue
    return tuple(instances)
