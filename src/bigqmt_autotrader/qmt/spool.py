from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Callable

from .protocol import MAX_FRAME_BYTES, QmtEvent, QmtProtocolError, decode_transport_frame
from .receiver import IngressResult, QmtIngressBuffer


DEFAULT_SPOOL_DIRNAME = "bigqmt_autotrader_spool"


def default_spool_root() -> Path:
    explicit = os.environ.get("BIGQMT_SPOOL_DIR")
    if explicit:
        return Path(explicit)
    return Path(tempfile.gettempdir()) / DEFAULT_SPOOL_DIRNAME


@dataclass(frozen=True)
class SpoolPollResult:
    processed: int
    quarantined: int
    pending: int

    @property
    def rejected(self) -> int:
        """Backward-compatible alias for the old pre-V05 name."""
        return self.quarantined


@dataclass(frozen=True)
class SpoolReplayResult:
    snapshot_found: bool
    replayed: int
    session_id: str | None = None
    last_sequence: int = 0
    account_fingerprint: str | None = None
    snapshot_timestamp_ms: int | None = None
    snapshot_sequence: int = 0
    target_sequence: int = 0
    target_timestamp_ms: int | None = None


@dataclass(frozen=True)
class _DecodedSpoolEvent:
    path: Path
    raw: bytes
    event: QmtEvent


class FileSpoolReceiver:
    """Consumes atomically published QMT event files from a local directory.

    QMT writes one complete transport frame to a temporary file and atomically
    renames it into ``inbox/*.json``. The host validates/ingests each file and
    then moves it to ``processed``. Malformed or protocol-invalid frames move to
    ``quarantine`` and are never silently deleted.

    ``processed`` also acts as the restart journal for the current unarchived
    day. A restarted Host may replay the coherent current session from its most
    recent clean snapshot without moving or deleting those files, then continue
    with new ``inbox`` events.

    The transport is deliberately one-way and read-only. It conveys broker facts
    but carries no command channel and therefore cannot grant execution authority.
    """

    def __init__(
        self,
        ingress: QmtIngressBuffer,
        *,
        spool_root: str | os.PathLike[str] | None = None,
        on_event: Callable[[IngressResult], None] | None = None,
    ) -> None:
        self.ingress = ingress
        self.root = Path(spool_root) if spool_root is not None else default_spool_root()
        self.inbox = self.root / "inbox"
        self.processed = self.root / "processed"
        self.quarantine = self.root / "quarantine"
        # Compatibility alias only. New code and documentation use quarantine.
        self.rejected = self.quarantine
        self.on_event = on_event
        for directory in (self.inbox, self.processed, self.quarantine):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _event_sort_key(item: _DecodedSpoolEvent) -> tuple[int, str, int, str]:
        return (
            item.event.timestamp_ms,
            item.event.session_id,
            item.event.sequence,
            item.path.name,
        )

    @staticmethod
    def _read_decoded(path: Path) -> _DecodedSpoolEvent:
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_FRAME_BYTES:
            raise QmtProtocolError("invalid transport frame size")
        return _DecodedSpoolEvent(path=path, raw=raw, event=decode_transport_frame(raw))

    def replay_processed_from_latest_clean_snapshot(self) -> SpoolReplayResult:
        """Rebuild Host state from the coherent current spool stream.

        Calibration can leave several historical QMT sessions/accounts in the
        same daily ``processed`` directory. Selecting the globally newest clean
        snapshot is therefore unsafe: replay can cross into an unrelated stream
        and fail account/session validation.

        Recovery first identifies the newest valid tail event across ``inbox``
        and ``processed`` (respecting an explicitly pinned account when present).
        It then selects only that tail event's session + account, finds the newest
        clean processed snapshot in that same stream, and replays processed events
        from that snapshot through the processed tail. Historical streams remain
        on disk for archive/quarantine inspection but do not contaminate live Host
        memory recovery.

        Invalid ``processed`` data is fail-closed. Invalid ``inbox`` candidates
        are ignored only for target selection; normal polling will quarantine them.
        Files are never moved, rewritten, or deleted by replay.
        """

        processed: list[_DecodedSpoolEvent] = []
        for path in sorted(self.processed.glob("*.json")):
            processed.append(self._read_decoded(path))

        inbox_valid: list[_DecodedSpoolEvent] = []
        for path in sorted(self.inbox.glob("*.json")):
            try:
                inbox_valid.append(self._read_decoded(path))
            except (OSError, QmtProtocolError):
                # Normal poll_once() owns quarantine/movement semantics.
                continue

        candidates = processed + inbox_valid
        expected = self.ingress.expected_account_fingerprint
        if expected is not None:
            candidates = [item for item in candidates if item.event.account_fingerprint == expected]
        if not candidates:
            return SpoolReplayResult(snapshot_found=False, replayed=0)

        target = max(candidates, key=self._event_sort_key)
        target_session = target.event.session_id
        target_account = target.event.account_fingerprint
        target_sequence = target.event.sequence

        coherent_processed = [
            item
            for item in processed
            if item.event.session_id == target_session
            and item.event.account_fingerprint == target_account
            and item.event.sequence <= target_sequence
        ]
        coherent_processed.sort(key=lambda item: (item.event.sequence, item.event.timestamp_ms, item.path.name))

        snapshot: _DecodedSpoolEvent | None = None
        for item in reversed(coherent_processed):
            if item.event.event_type == "snapshot" and not item.event.payload.get("query_errors"):
                snapshot = item
                break

        if snapshot is None:
            return SpoolReplayResult(
                snapshot_found=False,
                replayed=0,
                session_id=target_session,
                account_fingerprint=target_account,
                target_sequence=target_sequence,
                target_timestamp_ms=target.event.timestamp_ms,
            )

        replayed = 0
        for item in coherent_processed:
            if item.event.sequence < snapshot.event.sequence:
                continue
            result = self.ingress.ingest_frame(item.raw)
            if self.on_event is not None:
                self.on_event(result)
            replayed += 1

        return SpoolReplayResult(
            snapshot_found=True,
            replayed=replayed,
            session_id=self.ingress.session_id,
            last_sequence=self.ingress.last_sequence,
            account_fingerprint=self.ingress.expected_account_fingerprint,
            snapshot_timestamp_ms=snapshot.event.timestamp_ms,
            snapshot_sequence=snapshot.event.sequence,
            target_sequence=target_sequence,
            target_timestamp_ms=target.event.timestamp_ms,
        )

    def poll_once(self, *, max_files: int = 256) -> SpoolPollResult:
        if max_files <= 0:
            raise ValueError("max_files must be positive")

        processed = 0
        quarantined = 0
        candidates = sorted(self.inbox.glob("*.json"))[:max_files]
        for path in candidates:
            try:
                raw = path.read_bytes()
                if not raw or len(raw) > MAX_FRAME_BYTES:
                    raise QmtProtocolError("invalid transport frame size")
                result = self.ingress.ingest_frame(raw)
                if self.on_event is not None:
                    self.on_event(result)
            except QmtProtocolError:
                self._move_unique(path, self.quarantine)
                quarantined += 1
                continue
            except Exception:
                # Downstream ingestion failed. Leave the durable event in the
                # inbox and fail closed; retrying later is preferable to loss.
                raise
            else:
                self._move_unique(path, self.processed)
                processed += 1

        pending = sum(1 for _ in self.inbox.glob("*.json"))
        return SpoolPollResult(
            processed=processed,
            quarantined=quarantined,
            pending=pending,
        )

    def serve_forever(self, *, poll_interval_seconds: float = 0.2) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        while True:
            self.poll_once()
            time.sleep(poll_interval_seconds)

    @staticmethod
    def _move_unique(path: Path, target_dir: Path) -> Path:
        target = target_dir / path.name
        if target.exists():
            stem = path.stem
            suffix = path.suffix
            index = 1
            while target.exists():
                target = target_dir / f"{stem}.{index}{suffix}"
                index += 1
        shutil.move(str(path), str(target))
        return target
