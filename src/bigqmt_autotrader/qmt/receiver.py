from __future__ import annotations

from dataclasses import dataclass
import json
import socketserver
import threading
from typing import Callable

from .protocol import (
    IngressDisposition,
    MAX_FRAME_BYTES,
    QmtEvent,
    QmtProtocolError,
    decode_transport_frame,
)


@dataclass(frozen=True)
class IngressResult:
    disposition: IngressDisposition
    event: QmtEvent
    needs_resync: bool


class QmtIngressBuffer:
    """Validates account/session/sequence and detects replay or gaps fail-closed."""

    def __init__(self, *, expected_account_fingerprint: str | None = None) -> None:
        self.expected_account_fingerprint = expected_account_fingerprint
        self.session_id: str | None = None
        self.last_sequence = 0
        self.needs_resync = True
        self.events: list[QmtEvent] = []
        self._lock = threading.Lock()

    def ingest(self, event: QmtEvent) -> IngressResult:
        with self._lock:
            if (
                self.expected_account_fingerprint is not None
                and event.account_fingerprint != self.expected_account_fingerprint
            ):
                raise QmtProtocolError("unexpected account_fingerprint")

            if self.session_id != event.session_id:
                self.session_id = event.session_id
                self.last_sequence = 0
                self.needs_resync = True

            if event.sequence <= self.last_sequence:
                return IngressResult(
                    disposition=IngressDisposition.DUPLICATE,
                    event=event,
                    needs_resync=self.needs_resync,
                )

            disposition = IngressDisposition.ACCEPTED
            if self.last_sequence and event.sequence != self.last_sequence + 1:
                disposition = IngressDisposition.GAP
                self.needs_resync = True

            self.last_sequence = event.sequence
            self.events.append(event)

            # A complete active snapshot is the explicit resynchronization boundary.
            if event.event_type == "snapshot" and not event.payload.get("query_errors"):
                self.needs_resync = False

            return IngressResult(
                disposition=disposition,
                event=event,
                needs_resync=self.needs_resync,
            )

    def ingest_frame(self, raw: bytes) -> IngressResult:
        return self.ingest(decode_transport_frame(raw))

    def drain(self) -> list[QmtEvent]:
        with self._lock:
            events = list(self.events)
            self.events.clear()
            return events


class _ThreadingTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class LocalQmtReceiver:
    """Loopback-only TCP receiver. It never grants trading authority."""

    def __init__(
        self,
        ingress: QmtIngressBuffer,
        *,
        host: str = "127.0.0.1",
        port: int = 18765,
        on_event: Callable[[IngressResult], None] | None = None,
    ) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("QMT receiver must bind to loopback")
        self.ingress = ingress
        self.on_event = on_event

        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                raw = self.rfile.readline(MAX_FRAME_BYTES + 2)
                try:
                    if len(raw) > MAX_FRAME_BYTES:
                        raise QmtProtocolError("transport frame exceeds maximum size")
                    result = outer.ingress.ingest_frame(raw)
                    if outer.on_event is not None:
                        outer.on_event(result)
                    reply = {
                        "ok": True,
                        "disposition": result.disposition.value,
                        "needs_resync": result.needs_resync,
                        "sequence": result.event.sequence,
                    }
                except Exception as exc:
                    reply = {"ok": False, "error_type": type(exc).__name__}
                self.wfile.write((json.dumps(reply, separators=(",", ":")) + "\n").encode("utf-8"))

        self._server = _ThreadingTcpServer((host, port), Handler)
        self.host, self.port = self._server.server_address
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("receiver already started")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="bigqmt-readonly-receiver",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> "LocalQmtReceiver":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
