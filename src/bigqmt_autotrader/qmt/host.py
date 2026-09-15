from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import time
from typing import Any

from .archive import DailyArchiveResult, DailySpoolArchiver, SHANGHAI_TZ
from .ingestion import QmtHostIngestion
from .instances import DEFAULT_SPOOL_BASE, QmtInstance, QmtInstanceError, discover_instances, load_instance
from .receiver import IngressResult, LocalQmtReceiver, QmtIngressBuffer
from .spool import FileSpoolReceiver


STATUS_PREFIX = "BIGQMT_HOST_STATUS="
_ACTIVE_INSTANCE_ID: str | None = None


def _safe_status(status: str, payload: dict[str, Any]) -> None:
    if _ACTIVE_INSTANCE_ID is not None and "instance_id" not in payload:
        payload = {"instance_id": _ACTIVE_INSTANCE_ID, **payload}
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
        "session_id": event.session_id,
        "sequence": event.sequence,
        "disposition": result.disposition.value,
        "needs_resync": result.needs_resync,
        "read_model_healthy": ingestion.read_model.healthy,
        "quarantine_depth": len(ingestion.quarantine),
        "quarantine_dropped": ingestion.quarantine_dropped,
        "account_semantic_duplicates": ingestion.account_semantic_duplicates,
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
    elif event.event_type == "command_result":
        payload.update(
            {
                "command_id": event.payload.get("command_id"),
                "command_type": event.payload.get("command_type"),
                "client_order_id": event.payload.get("client_order_id"),
                "broker_token": event.payload.get("broker_token"),
                "result_status": event.payload.get("result_status"),
                "execution_mode": event.payload.get("execution_mode"),
                "live_side_effect": event.payload.get("live_side_effect"),
            }
        )
    elif event.event_type == "bridge_error":
        payload.update(
            {
                "code": event.payload.get("code"),
                "error_type": event.payload.get("error_type"),
            }
        )
    elif event.event_type == "order":
        payload.update(
            {
                "symbol": event.payload.get("symbol"),
                "broker_order_id": event.payload.get("broker_order_id"),
                "order_ref": event.payload.get("order_ref"),
                "remark": event.payload.get("remark"),
                "status_code": event.payload.get("status_code"),
                "submit_status_code": event.payload.get("submit_status_code"),
                "original_quantity": event.payload.get("original_quantity"),
                "filled_quantity": event.payload.get("filled_quantity"),
                "remaining_quantity": event.payload.get("remaining_quantity"),
            }
        )
    elif event.event_type == "deal":
        payload.update(
            {
                "symbol": event.payload.get("symbol"),
                "broker_order_id": event.payload.get("broker_order_id"),
                "order_ref": event.payload.get("order_ref"),
                "remark": event.payload.get("remark"),
                "trade_id": event.payload.get("trade_id"),
                "quantity": event.payload.get("quantity"),
                "price": event.payload.get("price"),
            }
        )
    elif event.event_type == "account_capabilities":
        records = event.payload.get("accounts", [])
        payload.update(
            {
                "selected_account_type": event.payload.get("selected_account_type"),
                "detected_account_types": event.payload.get("detected_account_types", []),
                "account_probe_count": len(records),
                "detected_account_count": sum(
                    1 for record in records if record.get("status") == "DETECTED"
                ),
                "degraded_account_count": sum(
                    1 for record in records if record.get("status") == "DEGRADED"
                ),
                "unconfirmed_account_count": sum(
                    1 for record in records if record.get("status") == "UNCONFIRMED"
                ),
            }
        )
    return payload


def _should_log_event(
    result: IngressResult,
    *,
    deduplicated: bool,
    quarantined: bool,
) -> bool:
    event_type = result.event.event_type
    if result.needs_resync or quarantined:
        return True
    if event_type in {
        "bridge_ready",
        "bridge_error",
        "snapshot",
        "account_capabilities",
        "order",
        "deal",
        "command_result",
    }:
        return True
    if event_type == "account" and not deduplicated:
        return True
    return False


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
) -> tuple[str, ...]:
    """Return only closed calendar days.

    QMT can keep emitting account heartbeats and reconciliation snapshots long
    after the A-share close. Same-day finalization therefore races a live
    producer. Automatic archive commit is deliberately delayed until the next
    UTC+08 calendar day; this makes the archive immutable without late-event
    ambiguity.
    """
    today = now.date().isoformat()
    return tuple(day for day in archiver.discover_processed_days() if day < today)


def _spool_dir_source(explicit_cli: str | None) -> str:
    if explicit_cli:
        return "cli"
    return "discovered_instance"


def _choose_instance(instances: tuple[QmtInstance, ...]) -> QmtInstance:
    print("Discovered valid QMT instances:", flush=True)
    for index, instance in enumerate(instances, start=1):
        print(
            f"[{index}] {instance.instance_id}  SHADOW  {instance.account_type}  "
            f"session={instance.session_id}",
            flush=True,
        )
    while True:
        try:
            selected = input("Select instance: ").strip()
        except EOFError as exc:
            raise SystemExit("--instance-id is required when stdin is not interactive") from exc
        if selected.isdigit() and 1 <= int(selected) <= len(instances):
            return instances[int(selected) - 1]
        print("Invalid selection.", flush=True)


def _resolve_spool_instance(args: argparse.Namespace) -> QmtInstance:
    if args.spool_dir:
        root = os.path.abspath(os.path.expanduser(args.spool_dir))
        instance_id = os.path.basename(root)
        if args.instance_id is not None and args.instance_id != instance_id:
            raise SystemExit("--instance-id must match the --spool-dir leaf name")
        try:
            return load_instance(os.path.dirname(root), instance_id)
        except QmtInstanceError as exc:
            raise SystemExit(str(exc)) from exc

    spool_base = os.path.abspath(os.path.expanduser(args.spool_base))
    if args.instance_id is not None:
        try:
            return load_instance(spool_base, args.instance_id)
        except QmtInstanceError as exc:
            raise SystemExit(str(exc)) from exc

    waiting_logged = False
    while True:
        instances = discover_instances(spool_base)
        if instances:
            return _choose_instance(instances)
        if not waiting_logged:
            _safe_status(
                "instance_waiting",
                {"spool_base": spool_base, "reason": "no_valid_instance_manifest"},
            )
            waiting_logged = True
        try:
            time.sleep(1.0)
        except KeyboardInterrupt as exc:
            raise SystemExit("instance discovery cancelled") from exc


def _status_summary_payload(
    stats: dict[str, int],
    ingestion: QmtHostIngestion,
    *,
    pending: int,
) -> dict[str, Any]:
    return {
        "events_seen": stats["events_seen"],
        "snapshots_seen": stats["snapshots_seen"],
        "account_capabilities_seen": stats.get("account_capabilities_seen", 0),
        "linked_accounts_observed": len(ingestion.read_model.linked_accounts),
        "account_events_seen": stats["account_events_seen"],
        "account_events_deduplicated": stats["account_events_deduplicated"],
        "position_events_seen": stats["position_events_seen"],
        "order_events_seen": stats["order_events_seen"],
        "deal_events_seen": stats["deal_events_seen"],
        "command_results_seen": stats.get("command_results_seen", 0),
        "semantic_quarantine_depth": len(ingestion.quarantine),
        "semantic_quarantine_dropped": ingestion.quarantine_dropped,
        "spool_processed_total": stats["spool_processed_total"],
        "spool_quarantined_total": stats["spool_quarantined_total"],
        "spool_pending": pending,
        "read_model_healthy": ingestion.read_model.healthy,
    }


def _summary_should_emit(
    payload: dict[str, Any],
    *,
    previous_payload: dict[str, Any] | None,
    monotonic_now: float,
    last_emit_monotonic: float,
    heartbeat_seconds: float,
) -> bool:
    if previous_payload is None or payload != previous_payload:
        return True
    return monotonic_now - last_emit_monotonic >= heartbeat_seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Big QMT P3/P4 host receiver")
    parser.add_argument(
        "--transport",
        choices=("spool", "tcp"),
        default="spool",
        help="spool is the production path; tcp is retained for tests/future runtimes",
    )
    parser.add_argument("--spool-dir", default=None)
    parser.add_argument("--spool-base", default=str(DEFAULT_SPOOL_BASE))
    parser.add_argument("--instance-id", default=None)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument(
        "--expected-account-fingerprint",
        default=None,
        help="Optional assertion; spool mode always pins the value from instance.json.",
    )
    parser.add_argument(
        "--auto-archive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Automatically compact closed-day processed spool files into daily archives.",
    )
    parser.add_argument("--archive-quiet-seconds", type=float, default=300.0)
    parser.add_argument("--archive-check-interval", type=float, default=30.0)
    parser.add_argument(
        "--status-summary-interval",
        type=float,
        default=300.0,
        help="Maximum seconds between unchanged status heartbeat summaries (default 300); changes emit immediately.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    global _ACTIVE_INSTANCE_ID
    args = build_parser().parse_args(argv)
    explicit_spool_dir = args.spool_dir
    if args.poll_interval <= 0:
        raise SystemExit("--poll-interval must be positive")
    if args.archive_quiet_seconds < 0:
        raise SystemExit("--archive-quiet-seconds must be non-negative")
    if args.archive_check_interval <= 0:
        raise SystemExit("--archive-check-interval must be positive")
    if args.status_summary_interval <= 0:
        raise SystemExit("--status-summary-interval must be positive")

    instance: QmtInstance | None = None
    expected_account_fingerprint = args.expected_account_fingerprint
    if args.transport == "spool":
        instance = _resolve_spool_instance(args)
        if (
            expected_account_fingerprint is not None
            and expected_account_fingerprint != instance.account_fingerprint
        ):
            raise SystemExit("--expected-account-fingerprint conflicts with instance.json")
        expected_account_fingerprint = instance.account_fingerprint
        args.spool_dir = str(instance.root)
        _ACTIVE_INSTANCE_ID = instance.instance_id

    ingress = QmtIngressBuffer(
        expected_account_fingerprint=expected_account_fingerprint,
        expected_terminal_instance_id=instance.instance_id if instance is not None else None,
    )
    ingestion = QmtHostIngestion()
    stats = {
        "events_seen": 0,
        "snapshots_seen": 0,
        "account_capabilities_seen": 0,
        "account_events_seen": 0,
        "account_events_deduplicated": 0,
        "position_events_seen": 0,
        "order_events_seen": 0,
        "deal_events_seen": 0,
        "command_results_seen": 0,
        "spool_processed_total": 0,
        "spool_quarantined_total": 0,
    }

    def on_event(result: IngressResult) -> None:
        ingest_result = ingestion.handle(result)
        event_type = result.event.event_type
        stats["events_seen"] += 1
        if event_type == "snapshot":
            stats["snapshots_seen"] += 1
        elif event_type == "account_capabilities":
            stats["account_capabilities_seen"] += 1
        elif event_type == "account":
            stats["account_events_seen"] += 1
            if ingest_result.deduplicated:
                stats["account_events_deduplicated"] += 1
        elif event_type == "position":
            stats["position_events_seen"] += 1
        elif event_type == "order":
            stats["order_events_seen"] += 1
        elif event_type == "deal":
            stats["deal_events_seen"] += 1
        elif event_type == "command_result":
            stats["command_results_seen"] += 1

        if _should_log_event(
            result,
            deduplicated=ingest_result.deduplicated,
            quarantined=ingest_result.quarantined,
        ):
            _safe_status(
                "event",
                {
                    **_event_summary(result, ingestion),
                    "evidence_ingested": ingest_result.evidence_ingested,
                    "command_result_ingested": ingest_result.command_result_ingested,
                    "calibration_observed": ingest_result.calibration_observed,
                    "quarantined": ingest_result.quarantined,
                    "deduplicated": ingest_result.deduplicated,
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
                    "explicit" if expected_account_fingerprint else "first_valid_event"
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
    resolved_spool_root = str(spool.root.expanduser().resolve())
    _safe_status(
        "ready",
        {
            "transport": "file_spool",
            "trading_enabled": False,
            "account_pin_mode": (
                "instance_manifest"
            ),
            "manifest_session_id": instance.session_id if instance is not None else None,
            "manifest_account_type": instance.account_type if instance is not None else None,
            "manifest_bridge_build": instance.bridge_build if instance is not None else None,
            "spool_root": resolved_spool_root,
            "spool_inbox": str(spool.inbox.resolve()),
            "spool_dir_source": _spool_dir_source(explicit_spool_dir),
            "auto_archive": args.auto_archive,
            "archive_policy": "past_days_only",
            "archive_quiet_seconds": args.archive_quiet_seconds,
            "archive_timezone": "UTC+08:00",
            "host_account_semantic_dedup": True,
            "event_log_mode": "important_only",
            "status_summary_mode": "change_driven_with_heartbeat",
            "status_summary_interval": args.status_summary_interval,
            "restart_replay": "coherent_current_session_from_latest_spool_tail",
        },
    )

    try:
        replay = spool.replay_processed_from_latest_clean_snapshot()
    except Exception as exc:
        _safe_status(
            "recovery_replay_error",
            {
                "error_type": type(exc).__name__,
                "read_model_healthy": ingestion.read_model.healthy,
            },
        )
    else:
        _safe_status(
            "recovery_replay",
            {
                "snapshot_found": replay.snapshot_found,
                "replayed": replay.replayed,
                "session_id": replay.session_id,
                "last_sequence": replay.last_sequence,
                "snapshot_sequence": replay.snapshot_sequence,
                "snapshot_timestamp_ms": replay.snapshot_timestamp_ms,
                "target_sequence": replay.target_sequence,
                "target_timestamp_ms": replay.target_timestamp_ms,
                "read_model_healthy": ingestion.read_model.healthy,
            },
        )

    last_archive_check = 0.0
    last_pending = sum(1 for _ in spool.inbox.glob("*.json"))
    last_archive_signature: dict[str, tuple[str, tuple[str, ...]]] = {}
    last_summary_emit = time.monotonic()
    last_summary_payload = _status_summary_payload(stats, ingestion, pending=last_pending)
    try:
        while True:
            try:
                result = spool.poll_once()
                stats["spool_processed_total"] += result.processed
                stats["spool_quarantined_total"] += result.quarantined
                last_pending = result.pending
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
            summary_payload = _status_summary_payload(stats, ingestion, pending=last_pending)
            if _summary_should_emit(
                summary_payload,
                previous_payload=last_summary_payload,
                monotonic_now=monotonic_now,
                last_emit_monotonic=last_summary_emit,
                heartbeat_seconds=args.status_summary_interval,
            ):
                _safe_status("summary", summary_payload)
                last_summary_payload = summary_payload
                last_summary_emit = monotonic_now

            if args.auto_archive and monotonic_now - last_archive_check >= args.archive_check_interval:
                last_archive_check = monotonic_now
                now = datetime.now(tz=SHANGHAI_TZ)
                for day in _archive_due_days(archiver, now=now):
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
