from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Callable

from .protocol import MAX_FRAME_BYTES, QmtProtocolError
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


class FileSpoolReceiver:
    """Consumes atomically published QMT event files from a local directory.

    QMT writes one complete transport frame to a temporary file and atomically
    renames it into ``inbox/*.json``. The host validates/ingests each file and
    then moves it to ``processed``. Malformed or protocol-invalid frames move to
    ``quarantine`` and are never silently deleted.

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
