from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import time

from .commands import QmtCommandSpool
from .instances import QmtInstanceError, load_instance


CONFIRMATION = "AUTHORIZE_SIMULATION_CALIBRATION"


def _cancel_command_id(
    account_fingerprint: str, client_order_id: str, broker_order_id: str
) -> str:
    digest = hashlib.sha256(
        (
            account_fingerprint
            + "\0"
            + client_order_id
            + "\0"
            + broker_order_id
        ).encode("utf-8")
    ).hexdigest()
    return "simcancel-" + digest[:32]


def _existing_cancel_path(
    spool: QmtCommandSpool,
    *,
    account_fingerprint: str,
    client_order_id: str,
    broker_order_id: str,
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
                frame = json.loads(path.read_text(encoding="utf-8"))
                command = frame["command"]
            except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                continue
            if (
                command.get("command_type") == "CANCEL_ORDER"
                and command.get("account_fingerprint") == account_fingerprint
                and command.get("client_order_id") == client_order_id
                and isinstance(command.get("payload"), dict)
                and command["payload"].get("broker_order_id") == broker_order_id
            ):
                return path
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish tightly bounded broker-mutation commands to a manifest-pinned "
            "SIMULATION_CALIBRATION QMT instance."
        )
    )
    parser.add_argument("--spool-dir", required=True)
    parser.add_argument("--confirm", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit", help="Submit exactly 100 A-share BUY shares")
    submit.add_argument("--client-order-id", required=True)
    submit.add_argument("--symbol", required=True)
    submit.add_argument("--quantity", type=int, required=True)
    submit.add_argument("--limit-price", required=True)
    submit.add_argument("--ttl-seconds", type=int, default=15)

    cancel = sub.add_parser("cancel", help="Cancel an exact token-matched calibration order")
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
            allow_simulation_mutation=True,
        )
    except QmtInstanceError as exc:
        raise SystemExit(str(exc)) from exc
    if (
        instance.execution_mode != "SIMULATION_CALIBRATION"
        or not instance.simulation_only
        or not instance.trading_enabled
        or not instance.live_submit
        or not instance.live_cancel
    ):
        raise SystemExit("selected instance is not authorized for simulation calibration")
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
        if args.quantity != 100:
            raise SystemExit("simulation calibration submit requires exactly 100 shares")
        symbol_parts = args.symbol.split(".")
        if (
            len(symbol_parts) != 2
            or len(symbol_parts[0]) != 6
            or not symbol_parts[0].isdigit()
            or symbol_parts[1] not in {"SH", "SZ"}
        ):
            raise SystemExit("--symbol must be a six-digit .SH or .SZ A-share symbol")
        try:
            limit_price = Decimal(args.limit_price)
        except InvalidOperation as exc:
            raise SystemExit("--limit-price must be decimal text") from exc
        if not limit_price.is_finite() or limit_price <= 0 or limit_price > 100000:
            raise SystemExit("--limit-price is outside the simulation safety range")
        command = spool.publish_submit(
            account_fingerprint=instance.account_fingerprint,
            client_order_id=args.client_order_id,
            symbol=args.symbol,
            side="BUY",
            quantity=args.quantity,
            limit_price=args.limit_price,
            created_ms=now_ms,
            expires_ms=expires_ms,
            simulation_calibration=True,
            expected_qmt_session_id=instance.session_id,
        )
    else:
        existing = _existing_cancel_path(
            spool,
            account_fingerprint=instance.account_fingerprint,
            client_order_id=args.client_order_id,
            broker_order_id=args.broker_order_id,
        )
        if existing is not None:
            raise SystemExit(
                "cancel already published for this client_order_id and "
                "broker_order_id; reconcile or resolve manually: " + str(existing)
            )
        command = spool.publish_cancel(
            account_fingerprint=instance.account_fingerprint,
            client_order_id=args.client_order_id,
            broker_order_id=args.broker_order_id,
            created_ms=now_ms,
            expires_ms=expires_ms,
            command_id=_cancel_command_id(
                instance.account_fingerprint,
                args.client_order_id,
                args.broker_order_id,
            ),
            simulation_calibration=True,
            expected_qmt_session_id=instance.session_id,
        )

    print(
        json.dumps(
            {
                "mode": instance.execution_mode,
                "simulation_only": True,
                "live_side_effect_authorized": True,
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
