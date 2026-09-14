from __future__ import annotations

import argparse
from dataclasses import asdict
import gzip
import json
from pathlib import Path
from typing import Iterable

from .calibration import QmtBrokerTokenCalibration
from .protocol import QmtEvent, decode_transport_frame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only QMT ORDER/DEAL m_strRemark calibration report"
    )
    parser.add_argument("--spool-dir", required=True)
    parser.add_argument("--expected-account-fingerprint", required=True)
    parser.add_argument(
        "--client-order-id",
        action="append",
        default=[],
        help="Known durable OMS client order identity; may be repeated.",
    )
    parser.add_argument("--include-archives", action="store_true")
    parser.add_argument("--details", action="store_true")
    return parser


def _event_files(root: Path) -> Iterable[Path]:
    for directory_name in ("processed", "inbox"):
        directory = root / directory_name
        if directory.is_dir():
            yield from sorted(directory.glob("*.json"))


def _read_events(root: Path, *, include_archives: bool) -> Iterable[QmtEvent]:
    for path in _event_files(root):
        yield decode_transport_frame(path.read_bytes())
    if not include_archives:
        return
    archive = root / "archive"
    if not archive.is_dir():
        return
    for path in sorted(archive.glob("*_events.jsonl.gz")):
        with gzip.open(path, "rb") as handle:
            for raw in handle:
                yield decode_transport_frame(raw)


def build_report(
    *,
    spool_dir: str | Path,
    expected_account_fingerprint: str,
    client_order_ids: Iterable[str] = (),
    include_archives: bool = False,
    include_details: bool = False,
) -> dict:
    root = Path(spool_dir)
    if not root.is_dir():
        raise ValueError("spool directory does not exist")

    calibration = QmtBrokerTokenCalibration()
    registered_tokens = [
        calibration.register(expected_account_fingerprint, client_order_id)
        for client_order_id in client_order_ids
    ]
    event_frames = 0
    callback_rows = 0
    snapshot_rows = 0
    sessions: set[str] = set()

    for event in _read_events(root, include_archives=include_archives):
        if event.account_fingerprint != expected_account_fingerprint:
            raise ValueError("spool contains an unexpected account fingerprint")
        event_frames += 1
        sessions.add(event.session_id)
        if event.event_type in {"order", "deal"}:
            calibration.observe(event)
            callback_rows += 1
        elif event.event_type == "snapshot":
            snapshot_rows += len(calibration.observe_snapshot(event))

    summary = dict(calibration.summary())
    report = {
        "mode": "READ_ONLY_CALIBRATION",
        "spool_dir": str(root.resolve()),
        "account_fingerprint": expected_account_fingerprint,
        "event_frames_scanned": event_frames,
        "sessions": sorted(sessions),
        "callback_order_deal_rows": callback_rows,
        "snapshot_order_deal_rows": snapshot_rows,
        "registered_client_order_ids": len(registered_tokens),
        "registered_broker_tokens": registered_tokens,
        **summary,
    }
    if include_details:
        report["records"] = [asdict(record) for record in calibration.records]
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(
        spool_dir=args.spool_dir,
        expected_account_fingerprint=args.expected_account_fingerprint,
        client_order_ids=args.client_order_id,
        include_archives=args.include_archives,
        include_details=args.details,
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
