from __future__ import annotations

import argparse
import json
import os
import time

from .commands import QmtCommandSpool
from .spool import default_spool_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish P4 SHADOW commands only; never calls a broker trading API."
    )
    parser.add_argument(
        "--spool-dir",
        default=os.environ.get("BIGQMT_SPOOL_DIR") or str(default_spool_root()),
    )
    parser.add_argument("--account-fingerprint", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    snapshot = sub.add_parser("snapshot", help="Ask QMT V05 to emit a fresh read-only snapshot")
    snapshot.add_argument("--ttl-seconds", type=int, default=30)

    submit = sub.add_parser(
        "submit",
        help="Publish a SHADOW submit command; V05 does not call passorder",
    )
    submit.add_argument("--client-order-id", required=True)
    submit.add_argument("--symbol", required=True)
    submit.add_argument("--side", choices=("BUY", "SELL"), required=True)
    submit.add_argument("--quantity", type=int, required=True)
    submit.add_argument("--limit-price", required=True)
    submit.add_argument("--ttl-seconds", type=int, default=30)

    cancel = sub.add_parser(
        "cancel",
        help="Publish a SHADOW cancel command; V05 does not call a broker cancel API",
    )
    cancel.add_argument("--client-order-id", required=True)
    cancel.add_argument("--broker-order-id", required=True)
    cancel.add_argument("--ttl-seconds", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ttl_seconds <= 0:
        raise SystemExit("--ttl-seconds must be positive")
    now_ms = int(time.time() * 1000)
    expires_ms = now_ms + args.ttl_seconds * 1000
    spool = QmtCommandSpool(args.spool_dir)

    if args.command == "snapshot":
        command = spool.publish_snapshot_request(
            account_fingerprint=args.account_fingerprint,
            created_ms=now_ms,
            expires_ms=expires_ms,
        )
    elif args.command == "submit":
        command = spool.publish_submit(
            account_fingerprint=args.account_fingerprint,
            client_order_id=args.client_order_id,
            symbol=args.symbol,
            side=args.side,
            quantity=args.quantity,
            limit_price=args.limit_price,
            created_ms=now_ms,
            expires_ms=expires_ms,
        )
    else:
        command = spool.publish_cancel(
            account_fingerprint=args.account_fingerprint,
            client_order_id=args.client_order_id,
            broker_order_id=args.broker_order_id,
            created_ms=now_ms,
            expires_ms=expires_ms,
        )

    print(
        json.dumps(
            {
                "mode": "SHADOW",
                "live_side_effect": False,
                "command_id": command.command_id,
                "command_type": command.command_type.value,
                "client_order_id": command.client_order_id,
                "broker_token": command.broker_token,
                "expires_ms": command.expires_ms,
                "command_inbox": str(spool.inbox),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
