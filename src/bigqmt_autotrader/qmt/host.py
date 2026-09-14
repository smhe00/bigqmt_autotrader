from __future__ import annotations

import argparse
from datetime import datetime, time as wall_time
import json
import time
from typing import Any

from .archive import DailyArchiveResult, DailySpoolArchiver, SHANGHAI_TZ
from .ingestion import QmtHostIngestion
from .receiver import IngressResult, LocalQmtReceiver, QmtIngressBuffer
from .spool import FileSpoolReceiver


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


def _parse_hhmm(value: str) -> wall_time:
    try:
        hour_text, minute_text = value.split(":", 1)
        return wall_time(hour=int(hour_text), minute=int(minute_text))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("expected HH:MM") from exc


def _archive_result_payload(result: DailyArchiveResult) -> dict[str, Any]:
    return {
        "trading_day": result.trading_day,
        "event_count": result.event_count,
        "deleted_files": result.deleted_files,
        "reasons": list(result.reasons),
        "archive_sha256": result.archive_sha256,
    }


def _archive_due_days(
    archiver: DailySpoolArchiver,
    *,
    now: datetime,
    archive_after: wall_time,
) -> tuple[str, ...]:
    today = now.date().isoformat()
    due: list[str] = []
    for day in archiver.discover_processed_days():
        if day < today:
            due.append(day)
        elif day == today and now.timetz().replace(tzinfo=None) >= archive_after:
            due.append(day)
    return tuple(due)


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
    parser.add_argument(
        "--auto-archive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Automatically compact processed spool files into daily archives.",
    )
    parser.add_argument(
        "--archive-after",
        type=_parse_hhmm,
        default=wall_time(hour=16, minute=10),
        help="A-share local time after which today's archive may commit (default 16:10).",
    )
    parser.add_argument("--archive-quiet-seconds", type=float, default=300.0)
    parser.add_argument("--archive-check-interval", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.poll_interval <= 0:
        raise SystemExit("--poll-interval must be positive")
    if args.archive_quiet_seconds < 0:
        raise SystemExit("--archive-quiet-seconds must be non-negative")
    if args.archive_check_interval <= 0:
        raise SystemExit("--archive-check-interval must be positive")

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
                "auto_archive": False,
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
    archiver = DailySpoolArchiver(spool_root=spool.root)
    _safe_status(
        "ready",
        {
            "transport": "file_spool",
            "trading_enabled": False,
            "account_pin_mode": (
                "explicit" if args.expected_account_fingerprint else "first_valid_event"
            ),
            "spool_dir_source": "explicit" if args.spool_dir else "default_temp",
            "auto_archive": args.auto_archive,
            "archive_after": args.archive_after.strftime("%H:%M"),
            "archive_quiet_seconds": args.archive_quiet_seconds,
            "archive_timezone": "UTC+08:00",
        },
    )

    last_archive_check = 0.0
    last_archive_signature: dict[str, tuple[str, tuple[str, ...]]] = {}
    try:
        while True:
            try:
                result = spool.poll_once()
                if result.quarantined:
                    _safe_status(
                        "spool_quarantined",
                        {"count": result.quarantined, "pending": result.pending},
                    )
            except Exception as exc:
                _safe_status(
                    "spool_error",
                    {"error_type": type(exc).__name__},
                )

            monotonic_now = time.monotonic()
            if args.auto_archive and monotonic_now - last_archive_check >= args.archive_check_interval:
                last_archive_check = monotonic_now
                now = datetime.now(tz=SHANGHAI_TZ)
                for day in _archive_due_days(
                    archiver,
                    now=now,
                    archive_after=args.archive_after,
                ):
                    try:
                        archive_result = archiver.archive_day(
                            day,
                            quiet_seconds=args.archive_quiet_seconds,
                            now_ms=int(now.timestamp() * 1000),
                        )
                    except Exception as exc:
                        _safe_status(
                            "archive_error",
                            {"trading_day": day, "error_type": type(exc).__name__},
                        )
                        continue

                    signature = (archive_result.status, archive_result.reasons)
                    if archive_result.status == "archived":
                        _safe_status("archive_committed", _archive_result_payload(archive_result))
                    elif archive_result.status == "already_archived":
                        if archive_result.deleted_files:
                            _safe_status("archive_recovered", _archive_result_payload(archive_result))
                    elif last_archive_signature.get(day) != signature:
                        _safe_status("archive_pending", _archive_result_payload(archive_result))
                    last_archive_signature[day] = signature

            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        _safe_status("stopping", {"reason": "keyboard_interrupt"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
