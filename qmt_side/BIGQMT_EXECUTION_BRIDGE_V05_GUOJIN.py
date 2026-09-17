#encoding:gbk
"""Big QMT P4/P5 bridge using durable local file spools.

Target: broker-neutral Big QMT built-in CPython 3.6.8 runtime.
No socket/thread/process dependency. The base template is SHADOW-only; the
deployment generator injects a tightly pinned simulation-calibration executor
only into the dedicated simulation artifact.

P4 shadow contract:
- broker-state callbacks publish immediately to the event spool;
- a 1-second run_time task scans durable Host commands;
- SUBMIT_LIMIT/CANCEL_ORDER commands are acknowledged in SHADOW only;
- a 300-second run_time task performs a full read-only snapshot reconcile;
- commands are atomically claimed before processing and orphaned claims are
  never blindly replayed after restart.
"""
from __future__ import print_function

# Deployment settings: edit these two lines when creating another standalone
# QMT instance. The instance ID becomes the spool child-directory name.
SPOOL_BASE_DIR = r"D:\BigQMTData\spool"
TERMINAL_INSTANCE_ID = "guojin"

# The deployment generator may replace this block only for an explicitly pinned
# mutation artifact. The generic template and Galaxy artifact stay fail-closed.
EXECUTION_MODE = "LIVE_CANARY"
TRADING_ENABLED = True
LIVE_SUBMIT_ENABLED = True
LIVE_CANCEL_ENABLED = True
SIMULATION_ONLY = False
AUTHORIZED_ACCOUNT_FINGERPRINT = "sha256:7cbd3cda92705081654ef838f9b93ab9f7928349ecf05fe97205c2d2948434e5"
SIMULATION_MAX_ORDER_QUANTITY = 100
SIMULATION_MAX_SUBMIT_CALLS = 1
SIMULATION_MAX_CANCEL_CALLS = 1

import hashlib
import json
import os
import sys
import time
import uuid

PROTOCOL_VERSION = "0.2"
TRANSPORT_VERSION = "1"
COMMAND_PROTOCOL_VERSION = "0.1"
COMMAND_TRANSPORT_VERSION = "1"
BRIDGE_BUILD = "p6-guojin-live-canary-4"
READ_ONLY_ENABLED = True
STATUS_PREFIX = "BIGQMT_RO_STATUS="
ACCOUNT_CALLBACK_HEARTBEAT_SECONDS = 300.0
COMMAND_TICK_PERIOD = "1nSecond"
SNAPSHOT_TIMER_PERIOD = "300nSecond"
TIMER_START = "2000-01-01 00:00:00"
MAX_QUEUED_EVENTS = 512
QUERY_TYPES = ("ACCOUNT", "POSITION", "ORDER", "DEAL")
STANDARD_ACCOUNT_TYPES = (
    "STOCK",
    "CREDIT",
    "FUTURE",
    "FUTURE_OPTION",
    "STOCK_OPTION",
    "HUGANGTONG",
    "SHENGANGTONG",
)
BROKER_TYPE_CODES = {
    "FUTURE": 1,
    "STOCK": 2,
    "CREDIT": 3,
    "FUTURE_OPTION": 5,
    "STOCK_OPTION": 6,
    "HUGANGTONG": 7,
    "SHENGANGTONG": 11,
}
TRANSPORT_MAX_FRAME_BYTES = 1024 * 1024
COMMAND_MAX_FRAME_BYTES = 64 * 1024
TRANSPORT_FLUSH_BATCH = 64
COMMAND_BATCH = 16
SPOOL_ROOT_OVERRIDE = None
INSTANCE_MANIFEST_VERSION = "1"
INSTANCE_MANIFEST_NAME = "instance.json"
COMMAND_TYPES = ("SUBMIT_LIMIT", "CANCEL_ORDER", "REQUEST_SNAPSHOT")


class BridgeError(RuntimeError):
    code = "E_BRIDGE"


class TradingDisabledError(BridgeError):
    code = "E_TRADING_DISABLED"


class ReadOnlyBridgeError(BridgeError):
    code = "E_READ_ONLY_BRIDGE"


class TransportError(BridgeError):
    code = "E_TRANSPORT"


class CommandError(BridgeError):
    code = "E_COMMAND"


class _RuntimeState(object):
    def __init__(self):
        self.account_id = None
        self.account_type = None
        self.account_fingerprint = None
        self.session_id = uuid.uuid4().hex
        self.sequence = 0
        self.initialized = False
        self.callback_subscription = False
        self.command_timer_registered = False
        self.snapshot_timer_registered = False
        self.events = []
        self.dropped_events = 0
        self.transport_persisted = 0
        self.transport_failures = 0
        self.last_transport_error_type = None
        self.spool_ready = False
        self.spool_root = None
        self.last_account_payload_digest = None
        self.last_account_state_monotonic = 0.0
        self.account_callbacks_suppressed = 0
        self.account_callbacks_emitted = 0
        self.detected_account_types = set()
        self.linked_account_callbacks_suppressed = 0
        self.orphan_recovery_done = False
        self.commands_claimed = 0
        self.commands_processed = 0
        self.commands_rejected = 0
        self.commands_unknown = 0
        self.simulation_submit_calls = 0
        self.simulation_cancel_calls = 0


_STATE = _RuntimeState()


def _spool_dir_source():
    if SPOOL_ROOT_OVERRIDE:
        return "test_override"
    return "embedded_instance"


def _spool_root():
    if SPOOL_ROOT_OVERRIDE:
        base = os.path.expanduser(SPOOL_ROOT_OVERRIDE)
    else:
        if not _valid_instance_id(TERMINAL_INSTANCE_ID):
            raise TransportError("unconfigured terminal instance")
        base = os.path.join(os.path.expanduser(SPOOL_BASE_DIR), TERMINAL_INSTANCE_ID)
    return os.path.abspath(os.path.normpath(base))


def _valid_instance_id(value):
    value = _text(value)
    if not value or len(value) > 32:
        return False
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-"
    return value == value.lower() and all(char in allowed for char in value)


def _spool_instance_id():
    return TERMINAL_INSTANCE_ID if _valid_instance_id(TERMINAL_INSTANCE_ID) else None


def _spool_inbox():
    return os.path.join(_spool_root(), "inbox")


def _command_root():
    return os.path.join(_spool_root(), "commands")


def _command_dir(name):
    return os.path.join(_command_root(), name)


def _ensure_dir(path):
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except OSError:
        if not os.path.isdir(path):
            raise
    return path


def _ensure_spool():
    root = _spool_root()
    inbox = _ensure_dir(os.path.join(root, "inbox"))
    for name in ("inbox", "claimed", "processed", "rejected", "unknown"):
        _ensure_dir(os.path.join(root, "commands", name))
    _STATE.spool_ready = True
    _STATE.spool_root = root
    return inbox


def _instance_manifest():
    return {
        "manifest_version": INSTANCE_MANIFEST_VERSION,
        "terminal_instance_id": _spool_instance_id(),
        "protocol_version": PROTOCOL_VERSION,
        "transport_version": TRANSPORT_VERSION,
        "bridge_build": BRIDGE_BUILD,
        "session_id": _STATE.session_id,
        "account_fingerprint": _STATE.account_fingerprint,
        "account_type": _text(_STATE.account_type),
        "created_ms": int(time.time() * 1000),
        "execution_mode": EXECUTION_MODE,
        "trading_enabled": TRADING_ENABLED,
        "live_submit": LIVE_SUBMIT_ENABLED,
        "live_cancel": LIVE_CANCEL_ENABLED,
        "simulation_only": SIMULATION_ONLY,
        "authorized_account_fingerprint": AUTHORIZED_ACCOUNT_FINGERPRINT,
        "max_order_quantity": SIMULATION_MAX_ORDER_QUANTITY,
        "max_submit_calls_per_session": SIMULATION_MAX_SUBMIT_CALLS,
        "max_cancel_calls_per_session": SIMULATION_MAX_CANCEL_CALLS,
    }


def _publish_instance_manifest():
    final_path = os.path.join(_spool_root(), INSTANCE_MANIFEST_NAME)
    temp_path = final_path + ".tmp-%d" % os.getpid()
    raw = (json.dumps(_instance_manifest(), ensure_ascii=True, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    try:
        handle = open(temp_path, "wb")
        try:
            handle.write(raw)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        finally:
            handle.close()
        _atomic_move(temp_path, final_path)
    except Exception:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        raise
    return final_path


def ping():
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "transport_version": TRANSPORT_VERSION,
        "bridge_build": BRIDGE_BUILD,
        "execution_mode": EXECUTION_MODE,
        "read_only_enabled": True,
        "trading_enabled": TRADING_ENABLED,
    }


def capabilities():
    return {
        "protocol_version": PROTOCOL_VERSION,
        "transport_version": TRANSPORT_VERSION,
        "command_protocol_version": COMMAND_PROTOCOL_VERSION,
        "command_transport_version": COMMAND_TRANSPORT_VERSION,
        "bridge_build": BRIDGE_BUILD,
        "execution_mode": EXECUTION_MODE,
        "read_only_enabled": True,
        "trading_enabled": TRADING_ENABLED,
        "live_submit": LIVE_SUBMIT_ENABLED,
        "live_cancel": LIVE_CANCEL_ENABLED,
        "simulation_only": SIMULATION_ONLY,
        "authorized_account_fingerprint": AUTHORIZED_ACCOUNT_FINGERPRINT,
        "max_order_quantity": SIMULATION_MAX_ORDER_QUANTITY,
        "max_submit_calls_per_session": SIMULATION_MAX_SUBMIT_CALLS,
        "max_cancel_calls_per_session": SIMULATION_MAX_CANCEL_CALLS,
        "shadow_commands": not TRADING_ENABLED,
        "command_tick_period": COMMAND_TICK_PERIOD,
        "snapshot_timer_period": SNAPSHOT_TIMER_PERIOD,
        "query_types": list(QUERY_TYPES),
        "account_type_probe_candidates": list(STANDARD_ACCOUNT_TYPES),
        "linked_account_discovery": "read_only_runtime_probe",
        "spool_isolation": "embedded_instance_namespace",
        "spool_instance_id": _spool_instance_id(),
        "callbacks": ["account", "position", "order", "deal"],
        "transport": "file_spool_atomic_rename",
        "command_transport": "file_spool_atomic_claim",
        "account_callback_dedup": True,
        "callback_account_identity_guard": True,
        "linked_account_callback_policy": "suppress_non_selected_detected_type",
        "account_callback_heartbeat_seconds": ACCOUNT_CALLBACK_HEARTBEAT_SECONDS,
        "methods": [
            "ping",
            "capabilities",
            "read_snapshot",
            "read_account_capabilities",
            "drain_events",
            "flush_transport",
        ],
    }


def submit_limit_order(*args, **kwargs):
    raise TradingDisabledError("P4 shadow safety gate: live order submission is disabled")


def cancel_order(*args, **kwargs):
    raise TradingDisabledError("P4 shadow safety gate: live order cancellation is disabled")


def _get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _text(value):
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def _decimal_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    try:
        return str(value)
    except Exception:
        return None


def _int_value(value):
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _symbol(obj):
    instrument = _text(_get(obj, "m_strInstrumentID"))
    exchange = _text(_get(obj, "m_strExchangeID"))
    if instrument and exchange:
        return instrument + "." + exchange
    return instrument


def _fingerprint(account_id, account_type):
    if not account_id:
        return None
    raw = (str(account_type or "") + ":" + str(account_id)).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _account_type(value):
    text = _text(value)
    return text.upper() if text else None


def _normalize_account(obj):
    return {
        "status": _text(_get(obj, "m_strStatus")),
        "balance": _decimal_text(_get(obj, "m_dBalance")),
        "available_cash": _decimal_text(_get(obj, "m_dAvailable")),
        "instrument_value": _decimal_text(_get(obj, "m_dInstrumentValue")),
        "stock_value": _decimal_text(_get(obj, "m_dStockValue")),
        "trading_date": _text(_get(obj, "m_strTradingDate")),
    }


def _normalize_position(obj):
    return {
        "symbol": _symbol(obj),
        "quantity": _int_value(_get(obj, "m_nVolume")),
        "sellable_quantity": _int_value(_get(obj, "m_nCanUseVolume")),
        "frozen_quantity": _int_value(_get(obj, "m_nFrozenVolume")),
        "on_road_quantity": _int_value(_get(obj, "m_nOnRoadVolume")),
        "market_value": _decimal_text(_get(obj, "m_dMarketValue")),
        "last_price": _decimal_text(_get(obj, "m_dLastPrice")),
        "open_price": _decimal_text(_get(obj, "m_dOpenPrice")),
        "trading_day": _text(_get(obj, "m_strTradingDay")),
    }


def _normalize_order(obj):
    return {
        "symbol": _symbol(obj),
        "order_ref": _text(_get(obj, "m_strOrderRef")),
        "broker_order_id": _text(_get(obj, "m_strOrderSysID")),
        "remark": _text(_get(obj, "m_strRemark")),
        "status_code": _int_value(_get(obj, "m_nOrderStatus")),
        "submit_status_code": _int_value(_get(obj, "m_nOrderSubmitStatus")),
        "original_quantity": _int_value(_get(obj, "m_nVolumeTotalOriginal")),
        "filled_quantity": _int_value(_get(obj, "m_nVolumeTraded")),
        "remaining_quantity": _int_value(_get(obj, "m_nVolumeTotal")),
        "cancelled_quantity": _decimal_text(_get(obj, "m_dCancelAmount")),
        "limit_price": _decimal_text(_get(obj, "m_dLimitPrice")),
        "average_fill_price": _decimal_text(_get(obj, "m_dTradedPrice")),
        "insert_date": _text(_get(obj, "m_strInsertDate")),
        "insert_time": _text(_get(obj, "m_strInsertTime")),
        "error_code": _int_value(_get(obj, "m_nErrorID")),
        "cancel_info": _text(_get(obj, "m_strCancelInfo")),
        "operation": _text(_get(obj, "m_strOptName")),
    }


def _normalize_deal(obj):
    return {
        "symbol": _symbol(obj),
        "trade_id": _text(_get(obj, "m_strTradeID")),
        "order_ref": _text(_get(obj, "m_strOrderRef")),
        "broker_order_id": _text(_get(obj, "m_strOrderSysID")),
        "remark": _text(_get(obj, "m_strRemark")),
        "price": _decimal_text(_get(obj, "m_dPrice")),
        "quantity": _int_value(_get(obj, "m_nVolume")),
        "trade_date": _text(_get(obj, "m_strTradeDate")),
        "trade_time": _text(_get(obj, "m_strTradeTime")),
        "commission": _decimal_text(_get(obj, "m_dCommission", _get(obj, "m_dComission"))),
        "trade_amount": _decimal_text(_get(obj, "m_dTradeAmount")),
        "operation": _text(_get(obj, "m_strOptName")),
    }


_NORMALIZERS = {
    "ACCOUNT": _normalize_account,
    "POSITION": _normalize_position,
    "ORDER": _normalize_order,
    "DEAL": _normalize_deal,
}


def _payload_digest(payload):
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _remember_account_state(payload, now=None):
    if now is None:
        now = time.monotonic()
    _STATE.last_account_payload_digest = _payload_digest(payload)
    _STATE.last_account_state_monotonic = now


def _event(event_type, source, payload):
    _STATE.sequence += 1
    return {
        "protocol_version": PROTOCOL_VERSION,
        "session_id": _STATE.session_id,
        "sequence": _STATE.sequence,
        "timestamp_ms": int(time.time() * 1000),
        "event_type": event_type,
        "source": source,
        "account_fingerprint": _STATE.account_fingerprint,
        "account_type": _text(_STATE.account_type),
        "terminal_instance_id": _spool_instance_id(),
        "payload": payload,
    }


def _safe_log(status, payload):
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "status": status,
        "terminal_instance_id": _spool_instance_id(),
        "account_fingerprint": _STATE.account_fingerprint,
        "payload": payload,
    }
    print(STATUS_PREFIX + json.dumps(body, ensure_ascii=True, sort_keys=True))


def _enqueue(event_type, source, payload):
    body = _event(event_type, source, payload)
    if len(_STATE.events) >= MAX_QUEUED_EVENTS:
        del _STATE.events[0]
        _STATE.dropped_events += 1
    _STATE.events.append(body)
    return body


def drain_events(max_items=None):
    if max_items is None:
        max_items = len(_STATE.events)
    try:
        max_items = max(0, int(max_items))
    except Exception:
        max_items = 0
    items = _STATE.events[:max_items]
    del _STATE.events[:max_items]
    return items


def _transport_frame(event):
    body = {"transport_version": TRANSPORT_VERSION, "event": event}
    raw = (json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > TRANSPORT_MAX_FRAME_BYTES:
        raise TransportError("event frame too large")
    return raw


def _event_filename(event):
    return "%013d_%s_%020d.json" % (
        int(event.get("timestamp_ms") or 0),
        str(event.get("session_id") or "nosession"),
        int(event.get("sequence") or 0),
    )


def _atomic_move(source, target):
    replacer = getattr(os, "replace", None)
    if callable(replacer):
        replacer(source, target)
    else:
        os.rename(source, target)


def _persist_event(event):
    inbox = _ensure_spool()
    final_path = os.path.join(inbox, _event_filename(event))
    if os.path.isfile(final_path):
        return True
    temp_path = final_path + ".tmp-%d" % os.getpid()
    raw = _transport_frame(event)
    try:
        handle = open(temp_path, "wb")
        try:
            handle.write(raw)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        finally:
            handle.close()
        _atomic_move(temp_path, final_path)
        return True
    except Exception:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        raise


def flush_transport(max_items=TRANSPORT_FLUSH_BATCH):
    persisted = 0
    try:
        limit = min(len(_STATE.events), max(0, int(max_items)))
    except Exception:
        limit = 0
    while persisted < limit:
        try:
            _persist_event(_STATE.events[persisted])
        except Exception as exc:
            _STATE.transport_failures += 1
            _STATE.last_transport_error_type = type(exc).__name__
            break
        persisted += 1
    if persisted:
        del _STATE.events[:persisted]
        _STATE.transport_persisted += persisted
        _STATE.last_transport_error_type = None
    return persisted


def _present_fields(row):
    return sorted([key for key, value in row.items() if value is not None])


def _snapshot_summary(snapshot):
    return {
        "account_rows": len(snapshot["account"]),
        "position_rows": len(snapshot["positions"]),
        "order_rows": len(snapshot["orders"]),
        "deal_rows": len(snapshot["deals"]),
        "query_errors": list(snapshot["query_errors"]),
        "account_fields": _present_fields(snapshot["account"][0]) if snapshot["account"] else [],
        "position_fields": _present_fields(snapshot["positions"][0]) if snapshot["positions"] else [],
        "order_fields": _present_fields(snapshot["orders"][0]) if snapshot["orders"] else [],
        "deal_fields": _present_fields(snapshot["deals"][0]) if snapshot["deals"] else [],
        "queued_events": len(_STATE.events),
        "dropped_events": _STATE.dropped_events,
        "transport_persisted": _STATE.transport_persisted,
        "transport_failures": _STATE.transport_failures,
        "account_callbacks_suppressed": _STATE.account_callbacks_suppressed,
        "account_callbacks_emitted": _STATE.account_callbacks_emitted,
        "linked_account_callbacks_suppressed": _STATE.linked_account_callbacks_suppressed,
    }


def _runtime_error(code, exc=None, extra=None):
    payload = {"code": code}
    if exc is not None:
        payload["error_type"] = type(exc).__name__
    if extra:
        payload.update(extra)
    if _STATE.account_fingerprint is not None:
        _enqueue("bridge_error", "runtime", payload)
        flush_transport()
    _safe_log("bridge_error", payload)
    return payload


def _resolve_query_fn(query_fn=None):
    if query_fn is not None:
        return query_fn
    candidate = globals().get("get_trade_detail_data")
    if not callable(candidate):
        raise ReadOnlyBridgeError("get_trade_detail_data is unavailable")
    return candidate


def read_snapshot(account_id=None, account_type=None, query_fn=None, emit=True):
    account_id = account_id if account_id is not None else _STATE.account_id
    account_type = account_type if account_type is not None else _STATE.account_type
    if not account_id or not account_type:
        raise ReadOnlyBridgeError("QMT account binding is unavailable")
    query = _resolve_query_fn(query_fn)
    snapshot = {
        "account_fingerprint": _fingerprint(account_id, account_type),
        "account_type": _text(account_type),
        "account": [],
        "positions": [],
        "orders": [],
        "deals": [],
        "query_errors": [],
    }
    keys = {"ACCOUNT": "account", "POSITION": "positions", "ORDER": "orders", "DEAL": "deals"}
    for data_type in QUERY_TYPES:
        try:
            rows = query(account_id, account_type, data_type.lower())
            if rows is None:
                rows = []
            snapshot[keys[data_type]] = [_NORMALIZERS[data_type](row) for row in list(rows)]
        except Exception as exc:
            snapshot["query_errors"].append({"data_type": data_type, "error_type": type(exc).__name__})
    if snapshot["account"]:
        _remember_account_state(snapshot["account"][0])
    if emit:
        _enqueue("snapshot", "active_query", snapshot)
        _safe_log("snapshot", _snapshot_summary(snapshot))
    return snapshot


def _account_probe_record(account_id, selected_account_type, candidate, query):
    record = {
        "account_type": candidate,
        "account_fingerprint": _fingerprint(account_id, candidate),
        "status": "UNCONFIRMED",
        "account": [],
        "positions": [],
        "query_errors": [],
    }
    try:
        account_rows = query(account_id, candidate, "account")
    except Exception as exc:
        record["query_errors"].append(
            {"data_type": "ACCOUNT", "error_code": "QUERY_EXCEPTION", "error_type": type(exc).__name__}
        )
        return record
    if account_rows is None:
        record["query_errors"].append(
            {"data_type": "ACCOUNT", "error_code": "QUERY_RETURNED_NONE"}
        )
        return record
    account_rows = list(account_rows)
    if not account_rows:
        record["query_errors"].append(
            {"data_type": "ACCOUNT", "error_code": "ACCOUNT_NOT_OBSERVED"}
        )
        return record

    expected_code = BROKER_TYPE_CODES.get(candidate)
    for row in account_rows:
        row_account_id = _text(_get(row, "m_strAccountID"))
        if row_account_id and row_account_id != _text(account_id):
            record["query_errors"].append(
                {"data_type": "ACCOUNT", "error_code": "ACCOUNT_ID_MISMATCH"}
            )
            return record
        broker_type = _int_value(_get(row, "m_nBrokerType"))
        if broker_type is None:
            if candidate != selected_account_type:
                record["query_errors"].append(
                    {"data_type": "ACCOUNT", "error_code": "BROKER_TYPE_UNAVAILABLE"}
                )
                return record
        elif expected_code is not None and broker_type != expected_code:
            record["query_errors"].append(
                {"data_type": "ACCOUNT", "error_code": "BROKER_TYPE_MISMATCH"}
            )
            return record

    record["account"] = [_normalize_account(row) for row in account_rows]
    record["status"] = "DETECTED"
    try:
        position_rows = query(account_id, candidate, "position")
    except Exception as exc:
        record["status"] = "DEGRADED"
        record["query_errors"].append(
            {"data_type": "POSITION", "error_code": "QUERY_EXCEPTION", "error_type": type(exc).__name__}
        )
        return record
    if position_rows is None:
        record["status"] = "DEGRADED"
        record["query_errors"].append(
            {"data_type": "POSITION", "error_code": "QUERY_RETURNED_NONE"}
        )
        return record
    record["positions"] = [_normalize_position(row) for row in list(position_rows)]
    return record


def read_account_capabilities(account_id=None, selected_account_type=None, query_fn=None, emit=True):
    """Probe standard QMT account types without identifying a broker vendor."""
    account_id = account_id if account_id is not None else _STATE.account_id
    selected_account_type = (
        selected_account_type if selected_account_type is not None else _STATE.account_type
    )
    selected_account_type = _account_type(selected_account_type)
    if not account_id or not selected_account_type:
        raise ReadOnlyBridgeError("QMT account binding is unavailable")
    query = _resolve_query_fn(query_fn)
    candidates = list(STANDARD_ACCOUNT_TYPES)
    if selected_account_type not in candidates:
        candidates.insert(0, selected_account_type)
    records = [
        _account_probe_record(account_id, selected_account_type, candidate, query)
        for candidate in candidates
    ]
    detected = [
        record["account_type"]
        for record in records
        if record["status"] in ("DETECTED", "DEGRADED")
    ]
    # Keep every type positively observed during this bridge session.  Some
    # terminals deliver ACCOUNT callbacks for all linked account types after a
    # model binds the shared fund account.  These observations must not enter
    # the selected OMS stream, but they are expected linked-account traffic and
    # must not create an error storm.
    _STATE.detected_account_types.update(detected)
    payload = {
        "selected_account_type": selected_account_type,
        "detected_account_types": detected,
        "accounts": records,
        "execution_mode": EXECUTION_MODE,
        "live_submit": LIVE_SUBMIT_ENABLED,
        "live_cancel": LIVE_CANCEL_ENABLED,
        "simulation_only": SIMULATION_ONLY,
    }
    if emit:
        _enqueue("account_capabilities", "active_query", payload)
        _safe_log(
            "account_capabilities",
            {
                "selected_account_type": selected_account_type,
                "detected_account_types": detected,
                "probe_count": len(records),
                "degraded_count": len(
                    [record for record in records if record["status"] == "DEGRADED"]
                ),
                "unconfirmed_count": len(
                    [record for record in records if record["status"] == "UNCONFIRMED"]
                ),
                "linked_account_callbacks_suppressed": _STATE.linked_account_callbacks_suppressed,
                "execution_mode": EXECUTION_MODE,
                "live_submit": LIVE_SUBMIT_ENABLED,
                "live_cancel": LIVE_CANCEL_ENABLED,
                "simulation_only": SIMULATION_ONLY,
            },
        )
    return payload


def _set_account_state(account_id, account_type):
    _STATE.account_id = account_id
    _STATE.account_type = account_type
    _STATE.account_fingerprint = _fingerprint(account_id, account_type)


def _register_timer(ContextInfo, callback_name, period):
    runner = _get(ContextInfo, "run_time")
    if not callable(runner):
        return False
    try:
        runner(callback_name, period, TIMER_START)
        return True
    except Exception as exc:
        _runtime_error("RUN_TIME_REGISTRATION_FAILED", exc, {"callback": callback_name, "period": period})
        return False


def _bind_runtime(ContextInfo):
    account_id = globals().get("account")
    account_type = globals().get("accountType")
    if not account_id or not account_type:
        _runtime_error("ACCOUNT_BINDING_UNAVAILABLE")
        return False
    _set_account_state(account_id, account_type)
    if TRADING_ENABLED:
        common_mutation_gate = (
            LIVE_SUBMIT_ENABLED is True
            and LIVE_CANCEL_ENABLED is True
            and _spool_instance_id() is not None
            and isinstance(AUTHORIZED_ACCOUNT_FINGERPRINT, str)
            and _STATE.account_fingerprint == AUTHORIZED_ACCOUNT_FINGERPRINT
            and _account_type(_STATE.account_type) == "STOCK"
            and SIMULATION_MAX_ORDER_QUANTITY == 100
        )
        mutation_gate_valid = common_mutation_gate and (
            (
                EXECUTION_MODE == "SIMULATION_CALIBRATION"
                and SIMULATION_ONLY is True
                and SIMULATION_MAX_SUBMIT_CALLS == 2
                and SIMULATION_MAX_CANCEL_CALLS == 2
            )
            or (
                EXECUTION_MODE == "LIVE_CANARY"
                and SIMULATION_ONLY is False
                and _spool_instance_id() == "guojin"
                and SIMULATION_MAX_SUBMIT_CALLS == 1
                and SIMULATION_MAX_CANCEL_CALLS == 1
            )
        )
        if not mutation_gate_valid:
            _runtime_error("MUTATION_GATE_INVALID")
            return False
    try:
        inbox = _ensure_spool()
    except Exception as exc:
        _runtime_error("SPOOL_INIT_FAILED", exc)
        return False
    setter = _get(ContextInfo, "set_account")
    if callable(setter):
        try:
            setter(account_id)
            _STATE.callback_subscription = True
        except Exception as exc:
            _STATE.callback_subscription = False
            _runtime_error("SET_ACCOUNT_FAILED", exc)
    else:
        _STATE.callback_subscription = False
        _runtime_error("SET_ACCOUNT_UNAVAILABLE")
    try:
        manifest_path = _publish_instance_manifest()
    except Exception as exc:
        _runtime_error("INSTANCE_MANIFEST_FAILED", exc)
        return False
    _STATE.initialized = True
    _STATE.command_timer_registered = _register_timer(ContextInfo, "command_tick", COMMAND_TICK_PERIOD)
    _STATE.snapshot_timer_registered = _register_timer(
        ContextInfo, "periodic_snapshot_timer", SNAPSHOT_TIMER_PERIOD
    )
    ready_event_payload = {
        "python_version": sys.version.split()[0],
        "callback_subscription": _STATE.callback_subscription,
        "command_timer_registered": _STATE.command_timer_registered,
        "snapshot_timer_registered": _STATE.snapshot_timer_registered,
        "spool_ready": _STATE.spool_ready,
        "capabilities": capabilities(),
    }
    instrument_subscribe = globals().get("_runtime_instrument_subscribe")
    if callable(instrument_subscribe):
        ready_event_payload["instrument_subscription"] = instrument_subscribe(ContextInfo)
    instrument_probe = globals().get("_runtime_instrument_probe")
    if callable(instrument_probe):
        ready_event_payload["instrument_probe"] = instrument_probe(ContextInfo)
    ready_log_payload = dict(ready_event_payload)
    ready_log_payload.update(
        {
            "spool_root": _STATE.spool_root,
            "spool_inbox": inbox,
            "command_inbox": _command_dir("inbox"),
            "instance_manifest": manifest_path,
            "spool_dir_source": _spool_dir_source(),
        }
    )
    _enqueue("bridge_ready", "init", ready_event_payload)
    _safe_log("bridge_ready", ready_log_payload)
    flush_transport()
    return True


def _read_command_frame(path):
    handle = open(path, "rb")
    try:
        raw = handle.read(COMMAND_MAX_FRAME_BYTES + 1)
    finally:
        handle.close()
    if not raw or len(raw) > COMMAND_MAX_FRAME_BYTES:
        raise CommandError("invalid command frame size")
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        raise CommandError("invalid command JSON")
    if not isinstance(body, dict) or body.get("command_transport_version") != COMMAND_TRANSPORT_VERSION:
        raise CommandError("unsupported command transport version")
    command = body.get("command")
    if not isinstance(command, dict):
        raise CommandError("missing command object")
    if command.get("command_protocol_version") != COMMAND_PROTOCOL_VERSION:
        raise CommandError("unsupported command protocol version")
    command_id = command.get("command_id")
    command_type = command.get("command_type")
    created_ms = command.get("created_ms")
    expires_ms = command.get("expires_ms")
    account_fingerprint = command.get("account_fingerprint")
    payload = command.get("payload")
    if not isinstance(command_id, str) or not command_id:
        raise CommandError("invalid command_id")
    if command_type not in COMMAND_TYPES:
        raise CommandError("unsupported command_type")
    if not isinstance(created_ms, int) or not isinstance(expires_ms, int) or expires_ms <= created_ms:
        raise CommandError("invalid command time window")
    if account_fingerprint != _STATE.account_fingerprint:
        raise CommandError("account fingerprint mismatch")
    if not isinstance(payload, dict):
        raise CommandError("invalid command payload")
    if command_type != "REQUEST_SNAPSHOT":
        client_order_id = command.get("client_order_id")
        broker_token = command.get("broker_token")
        if not isinstance(client_order_id, str) or not client_order_id:
            raise CommandError("missing client_order_id")
        if not isinstance(broker_token, str) or not broker_token or len(broker_token) >= 24:
            raise CommandError("invalid broker_token")
        expected_token = "BQ" + hashlib.sha256(
            (account_fingerprint + "\0" + client_order_id).encode("utf-8")
        ).hexdigest()[:20]
        if broker_token != expected_token:
            raise CommandError("broker_token identity mismatch")
    return command


def _command_result(command, result_status, live_side_effect=False):
    payload = {
        "command_id": command.get("command_id"),
        "command_type": command.get("command_type"),
        "client_order_id": command.get("client_order_id"),
        "broker_token": command.get("broker_token"),
        "result_status": result_status,
        "execution_mode": EXECUTION_MODE,
        "live_side_effect": bool(live_side_effect),
    }
    _enqueue("command_result", "command_spool", payload)
    _safe_log("command_result", payload)
    flush_transport()


def _recover_orphaned_claims():
    if _STATE.orphan_recovery_done:
        return
    _STATE.orphan_recovery_done = True
    claimed_dir = _command_dir("claimed")
    unknown_dir = _command_dir("unknown")
    try:
        names = sorted([name for name in os.listdir(claimed_dir) if name.endswith(".json")])
    except Exception as exc:
        _runtime_error("COMMAND_CLAIM_SCAN_FAILED", exc)
        return
    for name in names:
        source = os.path.join(claimed_dir, name)
        target = os.path.join(unknown_dir, name)
        try:
            command = _read_command_frame(source)
            _atomic_move(source, target)
            _STATE.commands_unknown += 1
            if TRADING_ENABLED and command.get("command_type") != "REQUEST_SNAPSHOT":
                orphaned = (
                    "LIVE_CANARY_ORPHANED_UNKNOWN"
                    if EXECUTION_MODE == "LIVE_CANARY"
                    else "SIMULATION_ORPHANED_UNKNOWN"
                )
                _command_result(command, orphaned, True)
            else:
                _command_result(command, "UNKNOWN_ORPHANED", False)
        except Exception as exc:
            try:
                if os.path.isfile(source):
                    _atomic_move(source, target)
            except Exception:
                pass
            _STATE.commands_unknown += 1
            _runtime_error("COMMAND_ORPHAN_RECOVERY_FAILED", exc, {"file": name})


def _reject_claimed(claimed_path, name, code, exc=None):
    target = os.path.join(_command_dir("rejected"), name)
    try:
        if os.path.isfile(claimed_path):
            _atomic_move(claimed_path, target)
    finally:
        _STATE.commands_rejected += 1
    _runtime_error(code, exc, {"file": name})


_LIVE_CANARY_INSTRUMENT_CANDIDATES = ("00700.HK", "00700.HGT", "00700.SGT")


def _runtime_instrument_probe(ContextInfo):
    query = None
    method = None
    for name in ("get_instrument_detail", "get_instrumentdetail"):
        candidate = getattr(ContextInfo, name, None)
        if callable(candidate):
            query = candidate
            method = name
            break
    records = []
    for symbol in _LIVE_CANARY_INSTRUMENT_CANDIDATES:
        record = {"symbol": symbol, "method": method, "observed": False}
        if query is None:
            record["error"] = "INSTRUMENT_QUERY_UNAVAILABLE"
        else:
            try:
                details = query(symbol)
                if isinstance(details, dict):
                    record.update(
                        {
                            "exchange_id": _text(details.get("ExchangeID")),
                            "exchange_code": _text(details.get("ExchangeCode")),
                            "instrument_id": _text(details.get("InstrumentID")),
                            "instrument_name": _text(details.get("InstrumentName")),
                            "is_trading": details.get("IsTrading"),
                            "hsgt_flag": details.get("HSGTFlag"),
                        }
                    )
                    record["observed"] = bool(
                        record["exchange_id"] and record["instrument_id"]
                    )
                else:
                    record["error"] = "INSTRUMENT_QUERY_INVALID_RESULT"
            except Exception as exc:
                record["error"] = "INSTRUMENT_QUERY_EXCEPTION"
                record["error_type"] = type(exc).__name__
        records.append(record)
    return {"candidates": records}


def _runtime_instrument_subscribe(ContextInfo):
    subscribe = getattr(ContextInfo, "subscribe_quote", None)
    records = []
    for symbol in _LIVE_CANARY_INSTRUMENT_CANDIDATES:
        record = {"symbol": symbol, "method": "subscribe_quote", "accepted": False}
        if not callable(subscribe):
            record["error"] = "SUBSCRIBE_QUOTE_UNAVAILABLE"
        else:
            try:
                subscription_id = subscribe(symbol, "tick")
                if isinstance(subscription_id, bool):
                    normalized_id = None
                else:
                    try:
                        normalized_id = int(subscription_id)
                    except Exception:
                        normalized_id = None
                record["subscription_id"] = normalized_id
                record["accepted"] = normalized_id is not None and normalized_id > 0
            except Exception as exc:
                record["error"] = "SUBSCRIBE_QUOTE_EXCEPTION"
                record["error_type"] = type(exc).__name__
        records.append(record)
    _STATE.instrument_probe_attempts = 0
    _STATE.instrument_probe_timer_registered = _register_timer(
        ContextInfo, "instrument_probe_tick", "1nSecond"
    )
    return {
        "candidates": records,
        "probe_timer_registered": _STATE.instrument_probe_timer_registered,
        "max_probe_attempts": 10,
    }


def instrument_probe_tick(ContextInfo):
    attempts = getattr(_STATE, "instrument_probe_attempts", 0)
    if attempts >= 10:
        return
    attempts += 1
    _STATE.instrument_probe_attempts = attempts
    payload = _runtime_instrument_probe(ContextInfo)
    payload["attempt"] = attempts
    payload["max_attempts"] = 10
    observed = any(record.get("observed") for record in payload["candidates"])
    if attempts == 1 or attempts == 10 or observed:
        _enqueue("instrument_capabilities", "active_query", payload)
        _safe_log("instrument_capabilities", payload)
        flush_transport()
    if observed:
        _STATE.instrument_probe_attempts = 10


def _live_canary_symbol(value):
    value = _text(value)
    if value != "00700.SGT":
        return None
    return value


def _live_canary_instrument_preflight(ContextInfo, symbol):
    details = None
    for name in ("get_instrument_detail", "get_instrumentdetail"):
        query = getattr(ContextInfo, name, None)
        if callable(query):
            details = query(symbol)
            break
    if not isinstance(details, dict) or not details:
        raise CommandError("live canary instrument preflight failed")
    exchange = _text(details.get("ExchangeID") or details.get("ExchangeCode"))
    instrument = _text(details.get("InstrumentID") or details.get("InstrumentCode"))
    if exchange != "SGT":
        raise CommandError("live canary instrument exchange mismatch")
    if instrument != "00700":
        raise CommandError("live canary instrument code mismatch")
    return details


def _live_canary_cancel_target(command):
    query = globals().get("get_trade_detail_data")
    if not callable(query):
        raise CommandError("order query unavailable")
    rows = query(_STATE.account_id, _STATE.account_type, "order")
    if rows is None:
        raise CommandError("order query returned None")
    broker_order_id = _text(command.get("payload", {}).get("broker_order_id"))
    broker_token = command.get("broker_token")
    matches = []
    for row in rows:
        if (
            _text(_get(row, "m_strOrderSysID")) == broker_order_id
            and _text(_get(row, "m_strRemark")) == broker_token
        ):
            matches.append(row)
    if len(matches) != 1:
        raise CommandError("live canary cancel target is not one exact token-matched order")
    return broker_order_id


def _execute_order_command(command, ContextInfo):
    if (
        TERMINAL_INSTANCE_ID != "guojin"
        or EXECUTION_MODE != "LIVE_CANARY"
        or TRADING_ENABLED is not True
        or SIMULATION_ONLY is not False
        or _STATE.account_fingerprint != AUTHORIZED_ACCOUNT_FINGERPRINT
        or _account_type(_STATE.account_type) != "STOCK"
    ):
        raise CommandError("live canary deployment gate is closed")

    payload = command.get("payload")
    if (
        not isinstance(payload, dict)
        or payload.get("live_canary") is not True
        or payload.get("simulation_calibration") is True
        or payload.get("expected_qmt_session_id") != _STATE.session_id
    ):
        raise CommandError("missing current-session live canary authorization")

    command_type = command.get("command_type")
    if command_type == "SUBMIT_LIMIT":
        if _STATE.simulation_submit_calls >= SIMULATION_MAX_SUBMIT_CALLS:
            raise CommandError("live canary submit session limit reached")
        symbol = _live_canary_symbol(payload.get("symbol"))
        quantity = payload.get("quantity")
        side = payload.get("side")
        try:
            price = float(payload.get("limit_price"))
        except Exception:
            raise CommandError("invalid live canary limit price")
        if symbol is None or side != "BUY" or quantity != 100:
            raise CommandError("live canary permits only 00700.SGT BUY 100")
        if price != 1.0:
            raise CommandError("live canary limit price must equal 1.00 HKD")
        _live_canary_instrument_preflight(ContextInfo, symbol)
        passorder(
            23,
            1101,
            _STATE.account_id,
            symbol,
            11,
            price,
            quantity,
            "BIGQMT_LIVE_CANARY",
            2,
            command.get("broker_token"),
            ContextInfo,
        )
        _STATE.simulation_submit_calls += 1
        return "LIVE_CANARY_SUBMIT_CALL_RETURNED", True

    if command_type == "CANCEL_ORDER":
        if _STATE.simulation_cancel_calls >= SIMULATION_MAX_CANCEL_CALLS:
            raise CommandError("live canary cancel session limit reached")
        broker_order_id = _live_canary_cancel_target(command)
        if not can_cancel_order(broker_order_id, _STATE.account_id, _STATE.account_type):
            return "LIVE_CANARY_CANCEL_NOT_CANCELLABLE", False
        result = cancel(broker_order_id, _STATE.account_id, _STATE.account_type, ContextInfo)
        _STATE.simulation_cancel_calls += 1
        if result is True:
            return "LIVE_CANARY_CANCEL_SIGNAL_SENT", True
        return "LIVE_CANARY_CANCEL_NOT_SENT", True

    raise CommandError("unsupported live canary mutation command")


def _process_claimed(claimed_path, name, ContextInfo):
    try:
        command = _read_command_frame(claimed_path)
    except Exception as exc:
        _reject_claimed(claimed_path, name, "COMMAND_REJECTED", exc)
        return

    if command.get("expires_ms") <= int(time.time() * 1000):
        target = os.path.join(_command_dir("rejected"), name)
        _atomic_move(claimed_path, target)
        _STATE.commands_rejected += 1
        _command_result(command, "REJECTED_EXPIRED")
        return

    command_type = command.get("command_type")
    if command_type == "REQUEST_SNAPSHOT":
        try:
            read_account_capabilities()
            read_snapshot()
            flush_transport()
            result_status = "SNAPSHOT_EMITTED"
        except Exception as exc:
            target = os.path.join(_command_dir("unknown"), name)
            _atomic_move(claimed_path, target)
            _STATE.commands_unknown += 1
            _runtime_error("COMMAND_SNAPSHOT_FAILED", exc, {"command_id": command.get("command_id")})
            return
    else:
        try:
            result_status, live_side_effect = _execute_order_command(command, ContextInfo)
        except CommandError as exc:
            target = os.path.join(_command_dir("rejected"), name)
            _atomic_move(claimed_path, target)
            _STATE.commands_rejected += 1
            _command_result(command, "REJECTED_SAFETY_GATE", False)
            _runtime_error(
                "COMMAND_SAFETY_GATE_REJECTED",
                exc,
                {
                    "command_id": command.get("command_id"),
                    "reason": _text(exc),
                },
            )
            return
        except Exception as exc:
            # Broker APIs are asynchronous. An exception cannot prove that no
            # mutation escaped, so fail to UNKNOWN and never retry.
            target = os.path.join(_command_dir("unknown"), name)
            _atomic_move(claimed_path, target)
            _STATE.commands_unknown += 1
            unknown = (
                "LIVE_CANARY_MUTATION_UNKNOWN"
                if EXECUTION_MODE == "LIVE_CANARY"
                else "SIMULATION_MUTATION_UNKNOWN"
            )
            _command_result(command, unknown, True)
            _runtime_error(
                "COMMAND_MUTATION_UNKNOWN",
                exc,
                {"command_id": command.get("command_id")},
            )
            return

    target = os.path.join(_command_dir("processed"), name)
    _atomic_move(claimed_path, target)
    _STATE.commands_processed += 1
    _command_result(command, result_status, live_side_effect if command_type != "REQUEST_SNAPSHOT" else False)


def _drain_command_inbox(ContextInfo, max_items=COMMAND_BATCH):
    _recover_orphaned_claims()
    inbox_dir = _command_dir("inbox")
    claimed_dir = _command_dir("claimed")
    try:
        names = sorted([name for name in os.listdir(inbox_dir) if name.endswith(".json")])[:max_items]
    except Exception as exc:
        _runtime_error("COMMAND_INBOX_SCAN_FAILED", exc)
        return 0
    claimed = 0
    for name in names:
        source = os.path.join(inbox_dir, name)
        target = os.path.join(claimed_dir, name)
        try:
            if os.path.isfile(target):
                _runtime_error("COMMAND_DUPLICATE_CLAIM", None, {"file": name})
                continue
            _atomic_move(source, target)
            _STATE.commands_claimed += 1
            claimed += 1
            _process_claimed(target, name, ContextInfo)
        except Exception as exc:
            if os.path.isfile(target):
                unknown = os.path.join(_command_dir("unknown"), name)
                try:
                    _atomic_move(target, unknown)
                except Exception:
                    pass
                _STATE.commands_unknown += 1
            _runtime_error("COMMAND_PROCESSING_UNKNOWN", exc, {"file": name})
    return claimed


def init(ContextInfo):
    if not _STATE.initialized:
        _bind_runtime(ContextInfo)


def after_init(ContextInfo):
    if not _STATE.initialized and not _bind_runtime(ContextInfo):
        return
    try:
        read_account_capabilities()
        read_snapshot()
        flush_transport()
    except Exception as exc:
        _runtime_error("INITIAL_SNAPSHOT_FAILED", exc)


def handlebar(ContextInfo):
    if not _STATE.initialized and not _bind_runtime(ContextInfo):
        return
    flush_transport()


def command_tick(ContextInfo):
    if not _STATE.initialized and not _bind_runtime(ContextInfo):
        return
    flush_transport()
    _drain_command_inbox(ContextInfo)


def periodic_snapshot_timer(ContextInfo):
    if not _STATE.initialized and not _bind_runtime(ContextInfo):
        return
    try:
        read_account_capabilities()
        read_snapshot()
        flush_transport()
    except Exception as exc:
        _runtime_error("PERIODIC_SNAPSHOT_FAILED", exc)


def _callback_event(event_type, payload, log_extra=None):
    _enqueue(event_type, "callback", payload)
    log_payload = {
        "event_type": event_type,
        "fields": _present_fields(payload),
        "queued_events": len(_STATE.events),
        "dropped_events": _STATE.dropped_events,
    }
    if log_extra:
        log_payload.update(log_extra)
    _safe_log("callback", log_payload)
    flush_transport()


def _callback_matches_selected_account(event_type, obj):
    observed_account_id = _text(_get(obj, "m_strAccountID"))
    if observed_account_id and observed_account_id != _text(_STATE.account_id):
        _runtime_error(
            "CALLBACK_ACCOUNT_ID_MISMATCH",
            None,
            {"event_type": event_type},
        )
        return False
    observed_broker_type = _int_value(_get(obj, "m_nBrokerType"))
    expected_broker_type = BROKER_TYPE_CODES.get(_account_type(_STATE.account_type))
    if (
        observed_broker_type is not None
        and expected_broker_type is not None
        and observed_broker_type != expected_broker_type
    ):
        detected_codes = set(
            BROKER_TYPE_CODES.get(account_type)
            for account_type in _STATE.detected_account_types
            if BROKER_TYPE_CODES.get(account_type) is not None
        )
        if observed_broker_type in detected_codes:
            # Preserve the single-account OMS callback contract.  The linked
            # account is already represented by account_capabilities; silently
            # suppress its callback instead of misrouting it or reporting a
            # false identity violation on every terminal heartbeat.
            _STATE.linked_account_callbacks_suppressed += 1
            return False
        _runtime_error(
            "CALLBACK_ACCOUNT_TYPE_MISMATCH",
            None,
            {"event_type": event_type, "observed_broker_type": observed_broker_type},
        )
        return False
    return True


def account_callback(ContextInfo, accountInfo):
    if not _callback_matches_selected_account("account", accountInfo):
        return
    payload = _normalize_account(accountInfo)
    now = time.monotonic()
    digest = _payload_digest(payload)
    same_payload = digest == _STATE.last_account_payload_digest
    heartbeat_due = (
        _STATE.last_account_state_monotonic <= 0.0
        or now - _STATE.last_account_state_monotonic >= ACCOUNT_CALLBACK_HEARTBEAT_SECONDS
    )
    if same_payload and not heartbeat_due:
        _STATE.account_callbacks_suppressed += 1
        return

    if _STATE.last_account_payload_digest is None:
        reason = "first"
    elif same_payload:
        reason = "heartbeat"
    else:
        reason = "changed"
    _remember_account_state(payload, now)
    _STATE.account_callbacks_emitted += 1
    _callback_event(
        "account",
        payload,
        {
            "dedup_reason": reason,
            "account_callbacks_suppressed": _STATE.account_callbacks_suppressed,
            "account_callbacks_emitted": _STATE.account_callbacks_emitted,
            "heartbeat_seconds": ACCOUNT_CALLBACK_HEARTBEAT_SECONDS,
        },
    )


def position_callback(ContextInfo, positionInfo):
    if not _callback_matches_selected_account("position", positionInfo):
        return
    _callback_event("position", _normalize_position(positionInfo))


def order_callback(ContextInfo, orderInfo):
    if not _callback_matches_selected_account("order", orderInfo):
        return
    _callback_event("order", _normalize_order(orderInfo))


def deal_callback(ContextInfo, dealInfo):
    if not _callback_matches_selected_account("deal", dealInfo):
        return
    _callback_event("deal", _normalize_deal(dealInfo))


def _top_level_bootstrap():
    namespace = globals()
    account_id = namespace.get("account")
    account_type = namespace.get("accountType")
    query_available = callable(namespace.get("get_trade_detail_data"))
    if account_id and account_type:
        _set_account_state(account_id, account_type)
    _safe_log(
        "module_loaded",
        {
            "python_version": sys.version.split()[0],
            "bridge_build": BRIDGE_BUILD,
            "execution_mode": EXECUTION_MODE,
            "account_injected": bool(account_id),
            "account_type_injected": bool(account_type),
            "query_available": query_available,
            "model_lifecycle_entered": False,
        },
    )
    if not (account_id and account_type and query_available):
        return
    try:
        inbox = _ensure_spool()
        read_snapshot(account_id, account_type)
        flush_transport()
        _safe_log(
            "top_level_snapshot_ok",
            {
                "callback_subscription": False,
                "spool_ready": True,
                "spool_root": _STATE.spool_root,
                "spool_inbox": inbox,
                "command_inbox": _command_dir("inbox"),
                "spool_dir_source": _spool_dir_source(),
            },
        )
    except Exception as exc:
        _runtime_error("TOP_LEVEL_SNAPSHOT_FAILED", exc)


_top_level_bootstrap()
