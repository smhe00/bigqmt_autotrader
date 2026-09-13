from __future__ import annotations

import argparse
import json
import time
from typing import Any

from .ingestion import QmtHostIngestion
from .receiver import IngressResult, LocalQmtReceiver, QmtIngressBuffer
from .spool import FileSpoolReceiver, default_spool_root


STATUS_PREFIX = "BIGQMT_HOST_STATUS="


def _safe_status(status: str, payload: dict[str, Any]) -> None:
    print(
        STATUS_PREFIX
        + json.dumps(
            {"status": status, "payload": payload},
            ensure_ascii=True,
            sort_keys=True,
        ),
        flush=True,
    )


def _event_summary(result: IngressResult, ingestion: QmtHostIngestion) -> dict[str, Any]:
    event = result.event
    payload: dict[str, Any] = {
        "event_type": event.event_type,
        "sequence": event.sequence,
        "disposition": result.disposition.value,
        "needs_resync": result.needs_resync,
        "read_model_healthy": ingestion.read_model.healthy,
        "quarantine_depth": len(ingestion.quarantine),
        "quarantine_dropped": ingestion.quarantine_dropped,
    }
    if event.event_type == "snapshot":
        payload.update(
            {
                "account_rows": len(event.payload.get("account", [])),
                "position_rows": len(event.payload.get("positions", [])),
                "order_rows": len(event.payload.get("orders", [])),
                "deal_rows": len(event.payload.get("deals", [])),
                "query_error_count": len(event.payload.get("query_errors", [])),
            }
        )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Big QMT P3 read-only host receiver")
    parser.add_argument(
        "--transport",
        choices=("spool", "tcp"),
        default="spool",
        help="spool is the Guojin QMT 2.1.19.0 production P3 path; tcp is retained for tests/future runtimes",
    )
    parser.add_argument("--spool-dir", default=None)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument(
        "--expected-account-fingerprint",
        default=None,
        help="Optional sha256:... fingerprint. If omitted, first valid event is pinned.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ingress = QmtIngressBuffer(
        expected_account_fingerprint=args.expected_account_fingerprint
    )
    ingestion = QmtHostIngestion()

    def on_event(result: IngressResult) -> None:
        ingest_result = ingestion.handle(result)
        _safe_status(
            "event",
            {
                **_event_summary(result, ingestion),
                "evidence_ingested": ingest_result.evidence_ingested,
                "quarantined": ingest_result.quarantined,
            },
        )

    if args.transport == "tcp":
        receiver = LocalQmtReceiver(
            ingress,
            host=args.host,
            port=args.port,
            on_event=on_event,
        )
        receiver.start()
        _safe_status(
            "ready",
            {
                "transport": "tcp",
                "host": receiver.host,
                "port": receiver.port,
                "trading_enabled": False,
                "account_pin_mode": (
                    "explicit" if args.expected_account_fingerprint else "first_valid_event"
                ),
            },
        )
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            _safe_status("stopping", {"reason": "keyboard_interrupt"})
        finally:
            receiver.close()
        return 0

    spool = FileSpoolReceiver(
        ingress,
        spool_root=args.spool_dir,
        on_event=on_event,
    )
    _safe_status(
        "ready",
        {
            "transport": "file_spool",
            "trading_enabled": False,
            "account_pin_mode": (
                "explicit" if args.expected_account_fingerprint else "first_valid_event"
            ),
            "spool_dir_source": "explicit" if args.spool_dir else "default_temp",
        },
    )
    try:
        while True:
            try:
                result = spool.poll_once()
                if result.rejected:
                    _safe_status(
                        "spool_rejected",
                        {"count": result.rejected, "pending": result.pending},
                    )
            except Exception as exc:
                _safe_status(
                    "spool_error",
                    {"error_type": type(exc).__name__},
                )
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        _safe_status("stopping", {"reason": "keyboard_interrupt"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
