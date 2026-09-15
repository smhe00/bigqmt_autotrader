from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Callable

from .protocol import MAX_FRAME_BYTES, QmtEvent, QmtProtocolError, decode_transport_frame
from .receiver import IngressResult, QmtIngressBuffer, QmtIngressIdentityError


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
    conflicted: int
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
class LegacyQuarantineInspection:
    valid_frames: int
    invalid_frames: int
    matching_target_frames: int
    matching_sequence_min: int | None = None
    matching_sequence_max: int | None = None
    matching_event_types: tuple[str, ...] = ()
    matching_clean_snapshot_sequences: tuple[int, ...] = ()


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
    ``quarantine`` and are never silently deleted. Valid transport frames that
    conflict with the Host's pinned account identity move to ``conflicts`` so
    they remain distinguishable from malformed data.

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
        self.conflicts = self.root / "conflicts"
        # Compatibility alias only. New code and documentation use quarantine.
        self.rejected = self.quarantine
        self.on_event = on_event
        for directory in (self.inbox, self.processed, self.quarantine, self.conflicts):
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

    def inspect_legacy_quarantine(
        self,
        *,
        session_id: str | None,
        account_fingerprint: str | None,
    ) -> LegacyQuarantineInspection:
        """Classify legacy quarantine without moving or trusting any file.

        Older Host builds conflated protocol errors with account identity
        conflicts, so ``quarantine`` may contain fully decodable events. This
        inspection is intentionally read-only: it only reports whether valid
        frames exist, and whether they belong to the current recovery target.
        """

        valid = 0
        invalid = 0
        matching: list[QmtEvent] = []
        for path in sorted(self.quarantine.glob("*.json")):
            try:
                item = self._read_decoded(path)
            except (OSError, QmtProtocolError):
                invalid += 1
                continue
            valid += 1
            event = item.event
            if (
                session_id is not None
                and account_fingerprint is not None
                and event.session_id == session_id
                and event.account_fingerprint == account_fingerprint
            ):
                matching.append(event)

        sequences = sorted(event.sequence for event in matching)
        event_types = tuple(sorted({event.event_type for event in matching}))
        clean_snapshots = tuple(
            sorted(
                event.sequence
                for event in matching
                if event.event_type == "snapshot" and not event.payload.get("query_errors")
            )
        )
        return LegacyQuarantineInspection(
            valid_frames=valid,
            invalid_frames=invalid,
            matching_target_frames=len(matching),
            matching_sequence_min=sequences[0] if sequences else None,
            matching_sequence_max=sequences[-1] if sequences else None,
            matching_event_types=event_types,
            matching_clean_snapshot_sequences=clean_snapshots,
        )

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
            result = self.ingress.ingest(item.event)
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
        conflicted = 0
        candidates = sorted(self.inbox.glob("*.json"))[:max_files]
        for path in candidates:
            try:
                item = self._read_decoded(path)
            except (OSError, QmtProtocolError):
                self._move_unique(path, self.quarantine)
                quarantined += 1
                continue

            try:
                result = self.ingress.ingest(item.event)
                if self.on_event is not None:
                    self.on_event(result)
            except QmtIngressIdentityError:
                self._move_unique(path, self.conflicts)
                conflicted += 1
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
            conflicted=conflicted,
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
