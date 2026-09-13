from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable

from .protocol import QmtEvent, QmtProtocolError, decode_transport_frame
from .spool import default_spool_root


SHANGHAI_TZ = timezone(timedelta(hours=8))
ARCHIVE_FORMAT_VERSION = "1"
_FILENAME_EPOCH_RE = re.compile(r"^(\d{13})_")


class ArchiveIntegrityError(RuntimeError):
    """A committed or candidate daily archive failed integrity validation."""


@dataclass(frozen=True)
class _SpoolRecord:
    path: Path
    raw: bytes
    event: QmtEvent
    trading_day: str


@dataclass(frozen=True)
class DailyArchiveResult:
    status: str
    trading_day: str
    event_count: int = 0
    deleted_files: int = 0
    reasons: tuple[str, ...] = ()
    archive_path: str | None = None
    manifest_path: str | None = None
    checkpoint_path: str | None = None
    archive_sha256: str | None = None


class DailySpoolArchiver:
    """Compacts successfully ingested QMT spool files into one daily archive.

    The durable small files in ``processed`` are the source set. They are only
    deleted after the gzip archive and manifest have been written atomically,
    re-read and verified, and a committed checkpoint has been persisted.

    A-share trading-day classification uses UTC+08:00 explicitly rather than
    the host machine timezone.
    """

    def __init__(self, *, spool_root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(spool_root) if spool_root is not None else default_spool_root()
        self.inbox = self.root / "inbox"
        self.processed = self.root / "processed"
        self.quarantine = self.root / "quarantine"
        self.archive = self.root / "archive"
        self.checkpoints = self.root / "checkpoints"
        for directory in (
            self.inbox,
            self.processed,
            self.quarantine,
            self.archive,
            self.checkpoints,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def event_trading_day(event: QmtEvent) -> str:
        observed = datetime.fromtimestamp(event.timestamp_ms / 1000.0, tz=SHANGHAI_TZ)
        return observed.date().isoformat()

    @staticmethod
    def shanghai_now() -> datetime:
        return datetime.now(tz=SHANGHAI_TZ)

    def discover_processed_days(self) -> tuple[str, ...]:
        days: set[str] = set()
        for path in self.processed.glob("*.json"):
            try:
                record = self._read_record(path)
            except (OSError, QmtProtocolError):
                hint = self._path_day_hint(path)
                if hint is not None:
                    days.add(hint)
            else:
                days.add(record.trading_day)
        return tuple(sorted(days))

    def archive_day(
        self,
        trading_day: str | date,
        *,
        quiet_seconds: float = 300.0,
        now_ms: int | None = None,
        require_final_snapshot: bool = True,
    ) -> DailyArchiveResult:
        day = self._normalize_day(trading_day)
        if quiet_seconds < 0:
            raise ValueError("quiet_seconds must be non-negative")
        if now_ms is None:
            now_ms = int(time.time() * 1000)

        archive_path = self.archive / f"{day}_events.jsonl.gz"
        manifest_path = self.archive / f"{day}_manifest.json"
        checkpoint_path = self.checkpoints / f"{day}.json"

        if checkpoint_path.exists():
            return self._recover_committed_day(
                day,
                archive_path=archive_path,
                manifest_path=manifest_path,
                checkpoint_path=checkpoint_path,
            )

        reasons: list[str] = []
        inbox_paths = self._paths_for_day(self.inbox, day)
        if inbox_paths:
            reasons.append("pending_inbox")
        quarantine_paths = self._paths_for_day(self.quarantine, day, tolerate_invalid=True)
        if quarantine_paths:
            reasons.append("quarantine_present")

        records: list[_SpoolRecord] = []
        corrupted_processed: list[Path] = []
        for path in sorted(self.processed.glob("*.json")):
            try:
                record = self._read_record(path)
            except (OSError, QmtProtocolError):
                if self._path_day_hint(path) == day:
                    corrupted_processed.append(path)
                continue
            if record.trading_day == day:
                records.append(record)

        if corrupted_processed:
            reasons.append("processed_corruption")
        if not records:
            return DailyArchiveResult(
                status="no_data" if not reasons else "not_ready",
                trading_day=day,
                reasons=tuple(sorted(set(reasons))),
            )

        records.sort(key=lambda item: (item.event.timestamp_ms, item.event.session_id, item.event.sequence))
        latest_ms = max(item.event.timestamp_ms for item in records)
        if now_ms < latest_ms + int(quiet_seconds * 1000):
            reasons.append("quiet_period")

        account_fingerprints = {item.event.account_fingerprint for item in records}
        if len(account_fingerprints) != 1:
            reasons.append("account_mismatch")

        gaps = self._sequence_gaps(records)
        if gaps:
            reasons.append("sequence_gap")

        final = records[-1].event
        if require_final_snapshot:
            if final.event_type != "snapshot":
                reasons.append("final_snapshot_missing")
            elif final.payload.get("query_errors"):
                reasons.append("final_snapshot_query_error")

        if reasons:
            return DailyArchiveResult(
                status="not_ready",
                trading_day=day,
                event_count=len(records),
                reasons=tuple(sorted(set(reasons))),
            )

        source_names = [record.path.name for record in records]
        event_stream_sha256 = self._stream_digest(record.raw for record in records)
        self._write_gzip_archive(archive_path, records)
        archive_sha256 = self._sha256_path(archive_path)

        sessions = self._session_summary(records)
        manifest: dict[str, Any] = {
            "archive_format_version": ARCHIVE_FORMAT_VERSION,
            "trading_day": day,
            "account_fingerprint": next(iter(account_fingerprints)),
            "event_count": len(records),
            "first_timestamp_ms": records[0].event.timestamp_ms,
            "last_timestamp_ms": records[-1].event.timestamp_ms,
            "sessions": sessions,
            "final_snapshot": {
                "session_id": final.session_id,
                "sequence": final.sequence,
                "timestamp_ms": final.timestamp_ms,
            },
            "archive_filename": archive_path.name,
            "archive_sha256": archive_sha256,
            "event_stream_sha256": event_stream_sha256,
            "source_file_count": len(source_names),
            "source_files": source_names,
            "source_files_sha256": hashlib.sha256(
                ("\n".join(source_names) + "\n").encode("utf-8")
            ).hexdigest(),
            "created_at_ms": int(time.time() * 1000),
        }
        self._atomic_write_json(manifest_path, manifest)

        self._verify_archive(archive_path, manifest)
        manifest_sha256 = self._sha256_path(manifest_path)
        checkpoint = {
            "status": "COMMITTED",
            "trading_day": day,
            "archive_filename": archive_path.name,
            "archive_sha256": archive_sha256,
            "manifest_filename": manifest_path.name,
            "manifest_sha256": manifest_sha256,
            "event_count": len(records),
            "committed_at_ms": int(time.time() * 1000),
        }
        self._atomic_write_json(checkpoint_path, checkpoint)

        # Verify once more after the commit marker exists. Only then may source
        # small files be deleted.
        self._verify_committed_files(archive_path, manifest_path, checkpoint_path)
        deleted = self._delete_exact_sources(records)
        return DailyArchiveResult(
            status="archived",
            trading_day=day,
            event_count=len(records),
            deleted_files=deleted,
            archive_path=str(archive_path),
            manifest_path=str(manifest_path),
            checkpoint_path=str(checkpoint_path),
            archive_sha256=archive_sha256,
        )

    def _recover_committed_day(
        self,
        day: str,
        *,
        archive_path: Path,
        manifest_path: Path,
        checkpoint_path: Path,
    ) -> DailyArchiveResult:
        manifest = self._verify_committed_files(archive_path, manifest_path, checkpoint_path)
        source_names = set(manifest.get("source_files", []))

        extras: list[str] = []
        for path in self._paths_for_day(self.processed, day):
            if path.name not in source_names:
                extras.append(path.name)
        if extras:
            return DailyArchiveResult(
                status="late_events",
                trading_day=day,
                event_count=int(manifest["event_count"]),
                reasons=("late_events_after_commit",),
                archive_path=str(archive_path),
                manifest_path=str(manifest_path),
                checkpoint_path=str(checkpoint_path),
                archive_sha256=str(manifest["archive_sha256"]),
            )

        deleted = 0
        for name in source_names:
            path = self.processed / name
            if path.exists():
                path.unlink()
                deleted += 1
        return DailyArchiveResult(
            status="already_archived",
            trading_day=day,
            event_count=int(manifest["event_count"]),
            deleted_files=deleted,
            archive_path=str(archive_path),
            manifest_path=str(manifest_path),
            checkpoint_path=str(checkpoint_path),
            archive_sha256=str(manifest["archive_sha256"]),
        )

    def _verify_committed_files(
        self,
        archive_path: Path,
        manifest_path: Path,
        checkpoint_path: Path,
    ) -> dict[str, Any]:
        if not (archive_path.exists() and manifest_path.exists() and checkpoint_path.exists()):
            raise ArchiveIntegrityError("committed archive set is incomplete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("status") != "COMMITTED":
            raise ArchiveIntegrityError("checkpoint is not committed")
        if self._sha256_path(manifest_path) != checkpoint.get("manifest_sha256"):
            raise ArchiveIntegrityError("manifest hash mismatch")
        if self._sha256_path(archive_path) != checkpoint.get("archive_sha256"):
            raise ArchiveIntegrityError("archive hash mismatch")
        self._verify_archive(archive_path, manifest)
        return manifest

    def _verify_archive(self, archive_path: Path, manifest: dict[str, Any]) -> None:
        if self._sha256_path(archive_path) != manifest.get("archive_sha256"):
            raise ArchiveIntegrityError("archive SHA-256 mismatch")
        raw_records: list[bytes] = []
        decoded: list[QmtEvent] = []
        try:
            with gzip.open(archive_path, "rb") as handle:
                for raw in handle:
                    raw_records.append(raw)
                    decoded.append(decode_transport_frame(raw))
        except (OSError, QmtProtocolError) as exc:
            raise ArchiveIntegrityError("archive payload is invalid") from exc
        if len(decoded) != int(manifest.get("event_count", -1)):
            raise ArchiveIntegrityError("archive event count mismatch")
        if self._stream_digest(raw_records) != manifest.get("event_stream_sha256"):
            raise ArchiveIntegrityError("archive event stream hash mismatch")
        day = str(manifest.get("trading_day"))
        if any(self.event_trading_day(event) != day for event in decoded):
            raise ArchiveIntegrityError("archive contains a different trading day")

    def _write_gzip_archive(self, final_path: Path, records: Iterable[_SpoolRecord]) -> None:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = final_path.with_name(final_path.name + f".tmp-{os.getpid()}")
        try:
            with open(temp_path, "wb") as raw_handle:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as zipped:
                    for record in records:
                        raw = record.raw if record.raw.endswith(b"\n") else record.raw + b"\n"
                        zipped.write(raw)
                raw_handle.flush()
                os.fsync(raw_handle.fileno())
            os.replace(temp_path, final_path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    @staticmethod
    def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(path.name + f".tmp-{os.getpid()}")
        raw = (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with open(temp_path, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def _read_record(self, path: Path) -> _SpoolRecord:
        raw = path.read_bytes()
        event = decode_transport_frame(raw)
        return _SpoolRecord(
            path=path,
            raw=raw,
            event=event,
            trading_day=self.event_trading_day(event),
        )

    def _paths_for_day(
        self,
        directory: Path,
        day: str,
        *,
        tolerate_invalid: bool = False,
    ) -> list[Path]:
        matched: list[Path] = []
        for path in directory.glob("*.json"):
            try:
                record = self._read_record(path)
            except (OSError, QmtProtocolError):
                if tolerate_invalid and self._path_day_hint(path) == day:
                    matched.append(path)
                continue
            if record.trading_day == day:
                matched.append(path)
        return sorted(matched)

    @staticmethod
    def _path_day_hint(path: Path) -> str | None:
        match = _FILENAME_EPOCH_RE.match(path.name)
        if match:
            try:
                timestamp_ms = int(match.group(1))
                return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=SHANGHAI_TZ).date().isoformat()
            except (OverflowError, OSError, ValueError):
                pass
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=SHANGHAI_TZ).date().isoformat()
        except OSError:
            return None

    @staticmethod
    def _normalize_day(value: str | date) -> str:
        if isinstance(value, date):
            return value.isoformat()
        return date.fromisoformat(value).isoformat()

    @staticmethod
    def _sequence_gaps(records: Iterable[_SpoolRecord]) -> list[tuple[str, int, int]]:
        per_session: dict[str, list[int]] = {}
        for record in records:
            per_session.setdefault(record.event.session_id, []).append(record.event.sequence)
        gaps: list[tuple[str, int, int]] = []
        for session_id, values in per_session.items():
            ordered = sorted(set(values))
            for left, right in zip(ordered, ordered[1:]):
                if right != left + 1:
                    gaps.append((session_id, left, right))
        return gaps

    @staticmethod
    def _session_summary(records: Iterable[_SpoolRecord]) -> list[dict[str, Any]]:
        per_session: dict[str, list[int]] = {}
        for record in records:
            per_session.setdefault(record.event.session_id, []).append(record.event.sequence)
        result: list[dict[str, Any]] = []
        for session_id in sorted(per_session):
            values = sorted(per_session[session_id])
            result.append(
                {
                    "session_id": session_id,
                    "first_sequence": values[0],
                    "last_sequence": values[-1],
                    "event_count": len(values),
                }
            )
        return result

    @staticmethod
    def _stream_digest(records: Iterable[bytes]) -> str:
        digest = hashlib.sha256()
        for raw in records:
            digest.update(raw if raw.endswith(b"\n") else raw + b"\n")
        return digest.hexdigest()

    @staticmethod
    def _sha256_path(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _delete_exact_sources(records: Iterable[_SpoolRecord]) -> int:
        deleted = 0
        for record in records:
            if record.path.exists():
                record.path.unlink()
                deleted += 1
        return deleted
