#encoding:gbk
"""One-shot read-only position probe for Big QMT model trading.

Bind this model to the ordinary stock account in the Model Trading UI.  Galaxy
QMT exposes the linked ordinary, Shanghai Stock Connect and Shenzhen Stock
Connect ledgers under the same account identifier and different account types.

The probe only reads the terminal cache.  It never subscribes callbacks and it
contains no broker mutation entry points.
"""
from __future__ import print_function

import hashlib
import json
import math
import time


STATUS_PREFIX = "BIGQMT_POSITION_PROBE="
ACCOUNT_TYPES = ("STOCK", "HUGANGTONG", "SHENGANGTONG")
_HAS_RUN = False


def _get(obj, name, default=None):
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return default if value is None else value


def _text(value):
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def _number(value):
    if value is None:
        return None
    try:
        result = float(value)
    except Exception:
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _integer(value):
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _symbol(obj):
    instrument = _text(_get(obj, "m_strInstrumentID"))
    exchange = _text(_get(obj, "m_strExchangeID"))
    if instrument and exchange and not instrument.endswith("." + exchange):
        return instrument + "." + exchange
    return instrument


def _fingerprint(account_id, account_type):
    raw = (str(account_type) + ":" + str(account_id)).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _position(obj):
    market_value = _get(obj, "m_dMarketValue")
    if market_value is None:
        market_value = _get(obj, "m_dInstrumentValue")
    return {
        "symbol": _symbol(obj),
        "name": _text(_get(obj, "m_strInstrumentName")),
        "quantity": _integer(_get(obj, "m_nVolume")),
        "sellable_quantity": _integer(_get(obj, "m_nCanUseVolume")),
        "frozen_quantity": _integer(_get(obj, "m_nFrozenVolume")),
        "on_road_quantity": _integer(_get(obj, "m_nOnRoadVolume")),
        "cost_price": _number(_get(obj, "m_dOpenPrice")),
        "last_price": _number(_get(obj, "m_dLastPrice")),
        "market_value": _number(market_value),
        "position_cost": _number(_get(obj, "m_dPositionCost")),
        "position_profit": _number(_get(obj, "m_dPositionProfit")),
    }


def collect(account_id, query_fn):
    observed_at_ms = int(time.time() * 1000)
    accounts = []
    for account_type in ACCOUNT_TYPES:
        record = {
            "account_type": account_type,
            "account_fingerprint": _fingerprint(account_id, account_type),
            "status": "QUERY_FAILED",
            "positions": [],
        }
        try:
            rows = query_fn(account_id, account_type, "position")
            if rows is None:
                record["error_code"] = "POSITION_QUERY_RETURNED_NONE"
            else:
                record["positions"] = [_position(item) for item in rows]
                record["position_count"] = len(record["positions"])
                record["status"] = "OK"
        except Exception as exc:
            record["error_code"] = "POSITION_QUERY_EXCEPTION"
            record["error_type"] = type(exc).__name__
        accounts.append(record)
    return {
        "schema_version": "1",
        "mode": "BIGQMT_READ_ONLY",
        "observed_at_ms": observed_at_ms,
        "account_count": len(accounts),
        "accounts": accounts,
    }


def run_once(namespace=None):
    global _HAS_RUN
    if _HAS_RUN:
        return None
    if namespace is None:
        namespace = globals()
    account_id = namespace.get("account")
    query_fn = namespace.get("get_trade_detail_data")
    if not account_id or not callable(query_fn):
        payload = {
            "schema_version": "1",
            "mode": "BIGQMT_READ_ONLY",
            "status": "ACCOUNT_BINDING_UNAVAILABLE",
        }
        print(STATUS_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return payload
    _HAS_RUN = True
    payload = collect(account_id, query_fn)
    print(STATUS_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return payload


def init(ContextInfo):
    run_once()


def after_init(ContextInfo):
    run_once()


def handlebar(ContextInfo):
    return None


if globals().get("account") and callable(globals().get("get_trade_detail_data")):
    run_once()

