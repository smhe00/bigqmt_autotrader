#encoding:gbk
"""Loopback-only read-only transport helper for Guojin Big QMT.

Target: built-in Python 3.6.8.
No threads, subprocesses, order submission, or cancellation APIs.
"""

from __future__ import print_function

import json
import socket


TRANSPORT_VERSION = "1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765
DEFAULT_TIMEOUT_SECONDS = 0.05
MAX_FRAME_BYTES = 1024 * 1024
MAX_ACK_BYTES = 4096


class TransportError(RuntimeError):
    pass


def _encode_event(event):
    body = {
        "transport_version": TRANSPORT_VERSION,
        "event": event,
    }
    raw = (json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > MAX_FRAME_BYTES:
        raise TransportError("event frame too large")
    return raw


def send_event(
    event,
    host=DEFAULT_HOST,
    port=DEFAULT_PORT,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    """Send one event and require a positive host ACK before success."""
    if host not in ("127.0.0.1", "localhost"):
        raise TransportError("non-loopback host is forbidden")
    raw = _encode_event(event)
    sock = None
    try:
        sock = socket.create_connection((host, int(port)), float(timeout_seconds))
        sock.settimeout(float(timeout_seconds))
        sock.sendall(raw)
        try:
            sock.shutdown(socket.SHUT_WR)
        except Exception:
            pass
        chunks = []
        total = 0
        while total < MAX_ACK_BYTES:
            chunk = sock.recv(min(1024, MAX_ACK_BYTES - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if b"\n" in chunk:
                break
        if not chunks:
            raise TransportError("missing ACK")
        line = b"".join(chunks).split(b"\n", 1)[0]
        ack = json.loads(line.decode("utf-8"))
        if not isinstance(ack, dict) or not ack.get("ok"):
            raise TransportError("negative ACK")
        return ack
    except TransportError:
        raise
    except Exception as exc:
        raise TransportError(type(exc).__name__)
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def flush_event_queue(
    events,
    host=DEFAULT_HOST,
    port=DEFAULT_PORT,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    max_items=32,
):
    """Best-effort FIFO flush; failed event and later events remain queued."""
    if not isinstance(events, list):
        raise TypeError("events must be a list")
    sent = 0
    limit = min(len(events), max(0, int(max_items)))
    while sent < limit:
        try:
            send_event(
                events[sent],
                host=host,
                port=port,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            break
        sent += 1
    if sent:
        del events[:sent]
    return sent
