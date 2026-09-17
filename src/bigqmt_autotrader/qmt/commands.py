from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from typing import Any, Mapping


COMMAND_PROTOCOL_VERSION = "0.1"
COMMAND_TRANSPORT_VERSION = "1"
MAX_COMMAND_FRAME_BYTES = 64 * 1024
_ACCOUNT_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class QmtCommandError(ValueError):
    pass


class QmtCommandConflict(QmtCommandError):
    pass


class QmtCommandType(str, Enum):
    SUBMIT_LIMIT = "SUBMIT_LIMIT"
    CANCEL_ORDER = "CANCEL_ORDER"
    REQUEST_SNAPSHOT = "REQUEST_SNAPSHOT"


@dataclass(frozen=True)
class QmtCommand:
    command_id: str
    created_ms: int
    expires_ms: int
    account_fingerprint: str
    command_type: QmtCommandType
    client_order_id: str | None
    broker_token: str | None
    payload: Mapping[str, Any]

    def as_mapping(self) -> dict[str, Any]:
        return {
            "command_protocol_version": COMMAND_PROTOCOL_VERSION,
            "command_id": self.command_id,
            "created_ms": self.created_ms,
            "expires_ms": self.expires_ms,
            "account_fingerprint": self.account_fingerprint,
            "command_type": self.command_type.value,
            "client_order_id": self.client_order_id,
            "broker_token": self.broker_token,
            "payload": dict(self.payload),
        }


def broker_token_for(account_fingerprint: str, client_order_id: str) -> str:
    _validate_account_fingerprint(account_fingerprint)
    if not isinstance(client_order_id, str) or not client_order_id:
        raise QmtCommandError("client_order_id must be a non-empty string")
    digest = hashlib.sha256(
        (account_fingerprint + "\0" + client_order_id).encode("utf-8")
    ).hexdigest()
    # QMT userOrderId / m_strRemark calibration requires length < 24.
    return "BQ" + digest[:20]


def encode_command_frame(command: QmtCommand) -> bytes:
    _validate_command(command)
    body = {
        "command_transport_version": COMMAND_TRANSPORT_VERSION,
        "command": command.as_mapping(),
    }
    raw = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(raw) > MAX_COMMAND_FRAME_BYTES:
        raise QmtCommandError("command frame exceeds maximum size")
    return raw


class QmtCommandSpool:
    """Host-owned durable command publisher for the P4 QMT bridge.

    Publishing is persist-before-consume: a complete immutable command frame is
    fsync'd and atomically renamed into commands/inbox. QMT owns claiming and
    completion after that point. Reusing a command_id with different content is
    a hard conflict; an identical frame is idempotent.
    """

    _STATE_DIRS = ("inbox", "claimed", "processed", "rejected", "unknown")

    def __init__(self, spool_root: str | os.PathLike[str]) -> None:
        self.root = Path(spool_root).expanduser().resolve()
        self.commands_root = self.root / "commands"
        for name in self._STATE_DIRS:
            (self.commands_root / name).mkdir(parents=True, exist_ok=True)
        self.inbox = self.commands_root / "inbox"
        self.claimed = self.commands_root / "claimed"
        self.processed = self.commands_root / "processed"
        self.rejected = self.commands_root / "rejected"
        self.unknown = self.commands_root / "unknown"

    def publish_submit(
        self,
        *,
        account_fingerprint: str,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        limit_price: str,
        expires_ms: int,
        command_id: str | None = None,
        created_ms: int | None = None,
        order_style: str | None = None,
        market: str | None = None,
        route_hint: str | None = None,
        simulation_calibration: bool = False,
        live_canary: bool = False,
        expected_qmt_session_id: str | None = None,
    ) -> QmtCommand:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "limit_price": limit_price,
        }
        if order_style is not None:
            payload["order_style"] = order_style
        if market is not None:
            payload["market"] = market
        if route_hint is not None:
            payload["route_hint"] = route_hint
        if simulation_calibration and live_canary:
            raise QmtCommandError("command cannot be both simulation and live canary")
        if simulation_calibration or live_canary:
            payload.update(
                {
                    (
                        "simulation_calibration"
                        if simulation_calibration
                        else "live_canary"
                    ): True,
                    "expected_qmt_session_id": expected_qmt_session_id,
                }
            )
        command = self._build(
            command_type=QmtCommandType.SUBMIT_LIMIT,
            account_fingerprint=account_fingerprint,
            client_order_id=client_order_id,
            broker_token=broker_token_for(account_fingerprint, client_order_id),
            payload=payload,
            expires_ms=expires_ms,
            command_id=command_id,
            created_ms=created_ms,
        )
        self.publish(command)
        return command

    def publish_cancel(
        self,
        *,
        account_fingerprint: str,
        client_order_id: str,
        broker_order_id: str,
        expires_ms: int,
        command_id: str | None = None,
        created_ms: int | None = None,
        simulation_calibration: bool = False,
        live_canary: bool = False,
        expected_qmt_session_id: str | None = None,
    ) -> QmtCommand:
        payload: dict[str, Any] = {"broker_order_id": broker_order_id}
        if simulation_calibration and live_canary:
            raise QmtCommandError("command cannot be both simulation and live canary")
        if simulation_calibration or live_canary:
            payload.update(
                {
                    (
                        "simulation_calibration"
                        if simulation_calibration
                        else "live_canary"
                    ): True,
                    "expected_qmt_session_id": expected_qmt_session_id,
                }
            )
        command = self._build(
            command_type=QmtCommandType.CANCEL_ORDER,
            account_fingerprint=account_fingerprint,
            client_order_id=client_order_id,
            broker_token=broker_token_for(account_fingerprint, client_order_id),
            payload=payload,
            expires_ms=expires_ms,
            command_id=command_id,
            created_ms=created_ms,
        )
        self.publish(command)
        return command

    def publish_snapshot_request(
        self,
        *,
        account_fingerprint: str,
        expires_ms: int,
        command_id: str | None = None,
        created_ms: int | None = None,
    ) -> QmtCommand:
        command = self._build(
            command_type=QmtCommandType.REQUEST_SNAPSHOT,
            account_fingerprint=account_fingerprint,
            client_order_id=None,
            broker_token=None,
            payload={},
            expires_ms=expires_ms,
            command_id=command_id,
            created_ms=created_ms,
        )
        self.publish(command)
        return command

    def publish(self, command: QmtCommand) -> Path:
        raw = encode_command_frame(command)
        now_ms = int(time.time() * 1000)
        if command.expires_ms <= now_ms:
            raise QmtCommandError("refusing to publish an expired command")

        filename = command.command_id + ".json"
        existing = self._find_existing(filename)
        if existing is not None:
            if existing.read_bytes() == raw:
                return existing
            raise QmtCommandConflict("command_id already exists with different content")

        final_path = self.inbox / filename
        temp_path = self.inbox / (filename + ".tmp-" + uuid.uuid4().hex)
        try:
            with temp_path.open("wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, final_path)
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
        return final_path

    def _find_existing(self, filename: str) -> Path | None:
        for state in self._STATE_DIRS:
            candidate = self.commands_root / state / filename
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _build(
        *,
        command_type: QmtCommandType,
        account_fingerprint: str,
        client_order_id: str | None,
        broker_token: str | None,
        payload: Mapping[str, Any],
        expires_ms: int,
        command_id: str | None,
        created_ms: int | None,
    ) -> QmtCommand:
        if created_ms is None:
            created_ms = int(time.time() * 1000)
        if command_id is None:
            command_id = uuid.uuid4().hex
        return QmtCommand(
            command_id=command_id,
            created_ms=created_ms,
            expires_ms=expires_ms,
            account_fingerprint=account_fingerprint,
            command_type=command_type,
            client_order_id=client_order_id,
            broker_token=broker_token,
            payload=dict(payload),
        )


def _validate_account_fingerprint(value: str) -> None:
    if not isinstance(value, str) or not _ACCOUNT_FINGERPRINT_RE.fullmatch(value):
        raise QmtCommandError("invalid account_fingerprint")


def _validate_command(command: QmtCommand) -> None:
    if not isinstance(command, QmtCommand):
        raise TypeError("command must be QmtCommand")
    if not _COMMAND_ID_RE.fullmatch(command.command_id):
        raise QmtCommandError("invalid command_id")
    if isinstance(command.created_ms, bool) or not isinstance(command.created_ms, int) or command.created_ms <= 0:
        raise QmtCommandError("created_ms must be a positive integer")
    if isinstance(command.expires_ms, bool) or not isinstance(command.expires_ms, int):
        raise QmtCommandError("expires_ms must be an integer")
    if command.expires_ms <= command.created_ms:
        raise QmtCommandError("expires_ms must be after created_ms")
    _validate_account_fingerprint(command.account_fingerprint)
    if not isinstance(command.payload, Mapping):
        raise QmtCommandError("payload must be an object")

    if command.command_type is QmtCommandType.REQUEST_SNAPSHOT:
        if command.client_order_id is not None or command.broker_token is not None:
            raise QmtCommandError("snapshot request must not carry order identity")
        return

    if not isinstance(command.client_order_id, str) or not command.client_order_id:
        raise QmtCommandError("order command requires client_order_id")
    expected_token = broker_token_for(command.account_fingerprint, command.client_order_id)
    if command.broker_token != expected_token or len(expected_token) >= 24:
        raise QmtCommandError("invalid broker_token")

    if command.command_type is QmtCommandType.SUBMIT_LIMIT:
        symbol = command.payload.get("symbol")
        side = command.payload.get("side")
        quantity = command.payload.get("quantity")
        limit_price = command.payload.get("limit_price")
        if not isinstance(symbol, str) or not symbol:
            raise QmtCommandError("submit requires symbol")
        if side not in {"BUY", "SELL"}:
            raise QmtCommandError("submit side must be BUY or SELL")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise QmtCommandError("submit quantity must be positive integer")
        if not isinstance(limit_price, str) or not limit_price:
            raise QmtCommandError("submit limit_price must be text")
        order_style = command.payload.get("order_style")
        market = command.payload.get("market")
        route_hint = command.payload.get("route_hint")
        if order_style is not None and order_style != "LIMIT":
            raise QmtCommandError("submit order_style currently supports LIMIT only")
        if market is not None and market not in {"AUTO", "CN", "HK_CONNECT"}:
            raise QmtCommandError("unsupported submit market")
        if route_hint is not None and route_hint not in {"AUTO", "HGT", "SGT"}:
            raise QmtCommandError("unsupported submit route_hint")
        if route_hint in {"HGT", "SGT"} and market not in {None, "HK_CONNECT"}:
            raise QmtCommandError("HGT/SGT route_hint requires HK_CONNECT market")
    elif command.command_type is QmtCommandType.CANCEL_ORDER:
        broker_order_id = command.payload.get("broker_order_id")
        if not isinstance(broker_order_id, str) or not broker_order_id:
            raise QmtCommandError("cancel requires broker_order_id")

    if command.payload.get("simulation_calibration") is True:
        expected_session = command.payload.get("expected_qmt_session_id")
        if not isinstance(expected_session, str) or not expected_session:
            raise QmtCommandError("simulation calibration requires expected_qmt_session_id")
