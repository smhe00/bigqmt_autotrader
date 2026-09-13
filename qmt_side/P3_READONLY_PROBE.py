# -*- coding: utf-8 -*-
"""P3 read-only capability probe for Big QMT built-in Python.

Target environment: Guojin QMT 2.1.19.0.

Safety contract:
- no passorder / cancel / task mutation calls;
- no credentials;
- no raw account id in output;
- no cash, position quantity, order id, trade id, price or PnL values in output;
- no exception text or filesystem paths in output;
- read-only inspection plus get_trade_detail_data() queries only.

The script is intentionally compatible with Python 3.6-era syntax and standard
library modules because Big QMT's embedded runtime is not assumed to match the
host-side Python 3.12 development environment.
"""

from __future__ import print_function

import hashlib
import json
import platform
import sys


PROBE_VERSION = "p3-readonly-probe-v1"
PROBE_PREFIX = "P3_PROBE_JSON="
_QUERY_TYPES = ("ACCOUNT", "POSITION", "ORDER", "DEAL")
_ACCOUNT_ATTRS = ("accountid", "accid", "accountID", "account_id")
_ACCOUNT_TYPE_ATTRS = ("accountType", "account_type")
_MAX_ATTEMPTS = 3

# Introspection only. Presence is reported; none of these mutation functions is
# ever invoked by this probe.
_MUTATION_NAMES = (
    "passorder",
    "cancel",
    "cancel_order",
    "cancel_task",
    "pause_task",
    "resume_task",
)
_READONLY_NAMES = (
    "get_trade_detail_data",
    "get_value_by_order_id",
    "get_last_order_id",
    "can_cancel_order",
)

_probe_finished = False
_probe_attempts = 0
_runtime_emitted = False


def _emit(event, payload):
    body = {
        "probe_version": PROBE_VERSION,
        "event": event,
        "payload": payload,
    }
    print(PROBE_PREFIX + json.dumps(body, ensure_ascii=False, sort_keys=True))


def _public_schema(obj):
    if obj is None:
        return []
    try:
        names = dir(obj)
    except Exception:
        return []
    result = []
    for name in names:
        if name.startswith("m_"):
            result.append(name)
    return sorted(set(result))


def _context_schema(context):
    try:
        names = dir(context)
    except Exception:
        return []
    result = []
    for name in names:
        if name.startswith("_"):
            continue
        result.append(name)
    return sorted(set(result))


def _read_noncallable_attr(obj, names):
    for name in names:
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return name, text
    return None, None


def _account_hash(account_id):
    if not account_id:
        return None
    raw = account_id.encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()[:16]


def _runtime_payload():
    vi = sys.version_info
    return {
        "python_version": sys.version,
        "python_version_info": [vi[0], vi[1], vi[2]],
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
    }


def _capability_payload():
    namespace = globals()
    readonly = {}
    mutation = {}
    for name in _READONLY_NAMES:
        readonly[name] = callable(namespace.get(name))
    for name in _MUTATION_NAMES:
        mutation[name] = callable(namespace.get(name))
    return {
        "readonly_functions_present": readonly,
        "mutation_functions_present_but_never_called": mutation,
    }


def _query_schemas(context):
    """Return True once a bound account is visible and queries were attempted."""
    namespace = globals()
    query_fn = namespace.get("get_trade_detail_data")
    if not callable(query_fn):
        _emit("query_unavailable", {"reason": "get_trade_detail_data_not_callable"})
        return True

    account_attr, account_id = _read_noncallable_attr(context, _ACCOUNT_ATTRS)
    account_type_attr, account_type = _read_noncallable_attr(context, _ACCOUNT_TYPE_ATTRS)

    if not account_id:
        _emit(
            "query_skipped",
            {
                "reason": "no_bound_account_id_visible_on_ContextInfo",
                "account_attr_candidates": list(_ACCOUNT_ATTRS),
            },
        )
        return False

    if not account_type:
        account_type = "STOCK"
        account_type_attr = "fallback:STOCK"

    _emit(
        "account_binding",
        {
            "account_attr": account_attr,
            "account_hash": _account_hash(account_id),
            "account_type_attr": account_type_attr,
            "account_type": account_type,
        },
    )

    for data_type in _QUERY_TYPES:
        try:
            rows = query_fn(account_id, account_type, data_type)
            if rows is None:
                rows = []
            rows = list(rows)
            schema = []
            if rows:
                schema = _public_schema(rows[0])
            _emit(
                "query_schema",
                {
                    "data_type": data_type,
                    "row_count": len(rows),
                    "sample_schema": schema,
                },
            )
        except Exception as exc:
            _emit(
                "query_error",
                {
                    "data_type": data_type,
                    "error_type": type(exc).__name__,
                },
            )
    return True


def _run_probe(context, source):
    global _probe_attempts
    global _probe_finished
    global _runtime_emitted

    if _probe_finished:
        return
    if _probe_attempts >= _MAX_ATTEMPTS:
        _probe_finished = True
        return

    _probe_attempts += 1
    _emit(
        "probe_attempt",
        {
            "attempt": _probe_attempts,
            "source": source,
            "target": "Guojin QMT 2.1.19.0",
        },
    )

    if not _runtime_emitted:
        _emit("runtime", _runtime_payload())
        _emit("capabilities", _capability_payload())
        _emit("context_schema", {"attributes": _context_schema(context)})
        _runtime_emitted = True

    completed = _query_schemas(context)
    if completed:
        _emit("probe_complete", {"mutation_calls_made": 0})
        _probe_finished = True
    elif _probe_attempts >= _MAX_ATTEMPTS:
        _emit(
            "probe_incomplete",
            {
                "reason": "bound_account_not_visible_after_retries",
                "mutation_calls_made": 0,
            },
        )
        _probe_finished = True


def init(ContextInfo):
    _run_probe(ContextInfo, "init")


def after_init(ContextInfo):
    _run_probe(ContextInfo, "after_init")


def handlebar(ContextInfo):
    _run_probe(ContextInfo, "handlebar")


def order_callback(ContextInfo, orderInfo):
    _emit("order_callback_schema", {"sample_schema": _public_schema(orderInfo)})


def deal_callback(ContextInfo, dealInfo):
    _emit("deal_callback_schema", {"sample_schema": _public_schema(dealInfo)})


def account_callback(ContextInfo, accountInfo):
    _emit("account_callback_schema", {"sample_schema": _public_schema(accountInfo)})


def position_callback(ContextInfo, positionInfo):
    _emit("position_callback_schema", {"sample_schema": _public_schema(positionInfo)})
