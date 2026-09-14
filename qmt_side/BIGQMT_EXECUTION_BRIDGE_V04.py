#encoding:gbk
"""Big QMT P3 read-only bridge using durable local file spool.

Target: Guojin QMT 2.1.19.0, built-in CPython 3.6.8.
No socket/thread/process dependency. No trading mutation calls.
"""
from __future__ import print_function

import hashlib
import json
import os
import sys
import time
import uuid

PROTOCOL_VERSION = "0.2"
TRANSPORT_VERSION = "1"
BRIDGE_BUILD = "p3-file-spool-2"
TRADING_ENABLED = False
READ_ONLY_ENABLED = True
STATUS_PREFIX = "BIGQMT_RO_STATUS="
SNAPSHOT_INTERVAL_SECONDS = 60.0
ACCOUNT_CALLBACK_HEARTBEAT_SECONDS = 300.0
MAX_QUEUED_EVENTS = 512
QUERY_TYPES = ("ACCOUNT", "POSITION", "ORDER", "DEAL")
TRANSPORT_MAX_FRAME_BYTES = 1024 * 1024
TRANSPORT_FLUSH_BATCH = 64
SPOOL_DIRNAME = "bigqmt_autotrader_spool"


class BridgeError(RuntimeError):
    code = "E_BRIDGE"


class TradingDisabledError(BridgeError):
    code = "E_TRADING_DISABLED"


class ReadOnlyBridgeError(BridgeError):
    code = "E_READ_ONLY_BRIDGE"


class TransportError(BridgeError):
    code = "E_TRANSPORT"


class _RuntimeState(object):
    def __init__(self):
        self.account_id = None
        self.account_type = None
        self.account_fingerprint = None
        self.session_id = uuid.uuid4().hex
        self.sequence = 0
        self.initialized = False
        self.callback_subscription = False
        self.last_snapshot_monotonic = 0.0
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


_STATE = _RuntimeState()


def _spool_dir_source():
    if os.environ.get("BIGQMT_SPOOL_DIR"):
        return "environment"
    if os.environ.get("TEMP") or os.environ.get("TMP"):
        return "temp"
    return "cwd"


def _spool_root():
    explicit = os.environ.get("BIGQMT_SPOOL_DIR")
    if explicit:
        base = os.path.expanduser(explicit)
    else:
        base = os.environ.get("TEMP") or os.environ.get("TMP")
        if not base:
            base = os.getcwd()
        base = os.path.join(base, SPOOL_DIRNAME)
    return os.path.abspath(os.path.normpath(base))


def _spool_inbox():
    return os.path.join(_spool_root(), "inbox")


def _ensure_spool():
    root = _spool_root()
    inbox = os.path.join(root, "inbox")
    try:
        if not os.path.isdir(inbox):
            os.makedirs(inbox)
    except OSError:
        if not os.path.isdir(inbox):
            raise
    _STATE.spool_ready = True
    _STATE.spool_root = root
    return inbox


def ping():
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "transport_version": TRANSPORT_VERSION,
        "bridge_build": BRIDGE_BUILD,
        "read_only_enabled": True,
        "trading_enabled": False,
    }


def capabilities():
    return {
        "protocol_version": PROTOCOL_VERSION,
        "transport_version": TRANSPORT_VERSION,
        "bridge_build": BRIDGE_BUILD,
        "read_only_enabled": True,
        "trading_enabled": False,
        "live_submit": False,
        "live_cancel": False,
        "query_types": list(QUERY_TYPES),
        "callbacks": ["account", "position", "order", "deal"],
        "transport": "file_spool_atomic_rename",
        "account_callback_dedup": True,
        "account_callback_heartbeat_seconds": ACCOUNT_CALLBACK_HEARTBEAT_SECONDS,
        "methods": ["ping", "capabilities", "read_snapshot", "drain_events", "flush_transport"],
    }


def submit_limit_order(*args, **kwargs):
    raise TradingDisabledError("P3 safety gate: live order submission is disabled")


def cancel_order(*args, **kwargs):
    raise TradingDisabledError("P3 safety gate: live order cancellation is disabled")


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
        "payload": payload,
    }


def _safe_log(status, payload):
    body = {
        "protocol_version": PROTOCOL_VERSION,
        "status": status,
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
        replacer = getattr(os, "replace", None)
        if callable(replacer):
            replacer(temp_path, final_path)
        else:
            os.rename(temp_path, final_path)
        return True
    except Exception:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        raise


def flush_transport(max_items=TRANSPORT_FLUSH_BATCH):
    """Persist queued events FIFO; remove only after atomic publication succeeds."""
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
    }


def _runtime_error(code, exc=None):
    payload = {"code": code}
    if exc is not None:
        payload["error_type"] = type(exc).__name__
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


def _set_account_state(account_id, account_type):
    _STATE.account_id = account_id
    _STATE.account_type = account_type
    _STATE.account_fingerprint = _fingerprint(account_id, account_type)


def _bind_runtime(ContextInfo):
    account_id = globals().get("account")
    account_type = globals().get("accountType")
    if not account_id or not account_type:
        _runtime_error("ACCOUNT_BINDING_UNAVAILABLE")
        return False
    _set_account_state(account_id, account_type)
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
    _STATE.initialized = True
    ready_event_payload = {
        "python_version": sys.version.split()[0],
        "callback_subscription": _STATE.callback_subscription,
        "spool_ready": _STATE.spool_ready,
        "capabilities": capabilities(),
    }
    ready_log_payload = dict(ready_event_payload)
    ready_log_payload.update(
        {
            "spool_root": _STATE.spool_root,
            "spool_inbox": inbox,
            "spool_dir_source": _spool_dir_source(),
        }
    )
    _enqueue("bridge_ready", "init", ready_event_payload)
    _safe_log("bridge_ready", ready_log_payload)
    flush_transport()
    return True


def init(ContextInfo):
    if not _STATE.initialized:
        _bind_runtime(ContextInfo)


def after_init(ContextInfo):
    if not _STATE.initialized and not _bind_runtime(ContextInfo):
        return
    try:
        read_snapshot()
        _STATE.last_snapshot_monotonic = time.monotonic()
        flush_transport()
    except Exception as exc:
        _runtime_error("INITIAL_SNAPSHOT_FAILED", exc)


def handlebar(ContextInfo):
    if not _STATE.initialized and not _bind_runtime(ContextInfo):
        return
    is_last_bar = _get(ContextInfo, "is_last_bar")
    if callable(is_last_bar):
        try:
            if not is_last_bar():
                return
        except Exception as exc:
            _runtime_error("IS_LAST_BAR_FAILED", exc)
            return
    flush_transport()
    now = time.monotonic()
    if now - _STATE.last_snapshot_monotonic < SNAPSHOT_INTERVAL_SECONDS:
        return
    try:
        read_snapshot()
        _STATE.last_snapshot_monotonic = now
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


def account_callback(ContextInfo, accountInfo):
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
    _callback_event("position", _normalize_position(positionInfo))


def order_callback(ContextInfo, orderInfo):
    _callback_event("order", _normalize_order(orderInfo))


def deal_callback(ContextInfo, dealInfo):
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
        _STATE.last_snapshot_monotonic = time.monotonic()
        flush_transport()
        _safe_log(
            "top_level_snapshot_ok",
            {
                "callback_subscription": False,
                "spool_ready": True,
                "spool_root": _STATE.spool_root,
                "spool_inbox": inbox,
                "spool_dir_source": _spool_dir_source(),
            },
        )
    except Exception as exc:
        _runtime_error("TOP_LEVEL_SNAPSHOT_FAILED", exc)


_top_level_bootstrap()
