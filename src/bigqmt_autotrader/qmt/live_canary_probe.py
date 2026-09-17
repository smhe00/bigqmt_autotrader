from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import time

from .commands import QmtCommandSpool
from .instances import QmtInstanceError, load_instance


CONFIRMATION = "AUTHORIZE_GUOJIN_LIVE_CANARY"
INSTANCE_ID = "guojin"
ACCOUNT_FINGERPRINT = (
    "sha256:7cbd3cda92705081654ef838f9b93ab9f7928349ecf05fe97205c2d2948434e5"
)
BRIDGE_BUILD = "p6-guojin-live-canary-1"
ALLOWED_SYMBOL = "00700.HK"


def _cancel_command_id(client_order_id: str, broker_order_id: str) -> str:
    digest = hashlib.sha256(
        (ACCOUNT_FINGERPRINT + "\0" + client_order_id + "\0" + broker_order_id).encode(
            "utf-8"
        )
    ).hexdigest()
    return "livecancel-" + digest[:32]


def _existing_cancel_path(
    spool: QmtCommandSpool, *, client_order_id: str, broker_order_id: str
) -> Path | None:
    for state_dir in (
        spool.inbox,
        spool.claimed,
        spool.processed,
        spool.rejected,
        spool.unknown,
    ):
        for path in state_dir.glob("*.json"):
            try:
                command = json.loads(path.read_text(encoding="utf-8"))["command"]
            except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                continue
            if (
                command.get("command_type") == "CANCEL_ORDER"
                and command.get("account_fingerprint") == ACCOUNT_FINGERPRINT
                and command.get("client_order_id") == client_order_id
                and isinstance(command.get("payload"), dict)
                and command["payload"].get("broker_order_id") == broker_order_id
            ):
                return path
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one tightly bounded Guojin production LIVE_CANARY command."
    )
    parser.add_argument("--spool-dir", required=True)
    parser.add_argument("--confirm", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit")
    submit.add_argument("--client-order-id", required=True)
    submit.add_argument("--symbol", required=True)
    submit.add_argument("--side", choices=("BUY", "SELL"), required=True)
    submit.add_argument("--quantity", type=int, required=True)
    submit.add_argument("--limit-price", required=True)
    submit.add_argument("--ttl-seconds", type=int, default=15)

    cancel = sub.add_parser("cancel")
    cancel.add_argument("--client-order-id", required=True)
    cancel.add_argument("--broker-order-id", required=True)
    cancel.add_argument("--ttl-seconds", type=int, default=15)
    return parser


def _load_authorized_instance(spool_dir: str):
    root = Path(spool_dir).expanduser().resolve()
    try:
        instance = load_instance(
            root.parent,
            root.name,
            allow_live_canary=True,
        )
    except QmtInstanceError as exc:
        raise SystemExit(str(exc)) from exc
    if (
        instance.instance_id != INSTANCE_ID
        or instance.account_fingerprint != ACCOUNT_FINGERPRINT
        or instance.bridge_build != BRIDGE_BUILD
        or instance.execution_mode != "LIVE_CANARY"
        or instance.simulation_only
        or not instance.trading_enabled
        or not instance.live_submit
        or not instance.live_cancel
    ):
        raise SystemExit("selected instance is not the pinned Guojin live canary")
    return instance


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.confirm != CONFIRMATION:
        raise SystemExit("--confirm must equal " + CONFIRMATION)
    if args.ttl_seconds <= 0 or args.ttl_seconds > 30:
        raise SystemExit("--ttl-seconds must be in 1..30")

    instance = _load_authorized_instance(args.spool_dir)
    now_ms = int(time.time() * 1000)
    expires_ms = now_ms + args.ttl_seconds * 1000
    spool = QmtCommandSpool(instance.root)

    if args.command == "submit":
        if (
            args.symbol != ALLOWED_SYMBOL
            or args.side != "BUY"
            or args.quantity != 100
        ):
            raise SystemExit("live canary permits only 00700.HK BUY 100")
        try:
            limit_price = Decimal(args.limit_price)
        except InvalidOperation as exc:
            raise SystemExit("--limit-price must be decimal text") from exc
        if not limit_price.is_finite() or limit_price != Decimal("1.00"):
            raise SystemExit("--limit-price must equal 1.00 HKD for the live canary")
        command = spool.publish_submit(
            account_fingerprint=instance.account_fingerprint,
            client_order_id=args.client_order_id,
            symbol=args.symbol,
            side=args.side,
            quantity=args.quantity,
            limit_price=args.limit_price,
            created_ms=now_ms,
            expires_ms=expires_ms,
            live_canary=True,
            expected_qmt_session_id=instance.session_id,
        )
    else:
        existing = _existing_cancel_path(
            spool,
            client_order_id=args.client_order_id,
            broker_order_id=args.broker_order_id,
        )
        if existing is not None:
            raise SystemExit("live canary cancel already published: " + str(existing))
        command = spool.publish_cancel(
            account_fingerprint=instance.account_fingerprint,
            client_order_id=args.client_order_id,
            broker_order_id=args.broker_order_id,
            created_ms=now_ms,
            expires_ms=expires_ms,
            command_id=_cancel_command_id(args.client_order_id, args.broker_order_id),
            live_canary=True,
            expected_qmt_session_id=instance.session_id,
        )

    print(
        json.dumps(
            {
                "mode": instance.execution_mode,
                "instance_id": instance.instance_id,
                "session_id": instance.session_id,
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
