from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05.py"
TOKEN = "__BIGQMT_INSTANCE_ID__"
SIMULATION_FINGERPRINT = "sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702"
GUOJIN_LIVE_FINGERPRINT = "sha256:7cbd3cda92705081654ef838f9b93ab9f7928349ecf05fe97205c2d2948434e5"
DEPLOYMENTS = {
    "galaxy": (ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py", "shadow"),
    "guojin": (ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py", "live_canary"),
    "guojin_sim": (ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py", "simulation"),
}

SHADOW_EXECUTOR = '''def _execute_order_command(command, ContextInfo):
    """SHADOW default replaced only in an explicitly pinned mutation artifact."""
    return "SHADOW_ACCEPTED", False
'''

SIMULATION_EXECUTOR = '''def _simulation_order_symbol(value):
    value = _text(value)
    if not value:
        return None
    parts = value.split(".")
    if len(parts) != 2 or not parts[0].isdigit():
        return None
    market = parts[1]
    if market in ("SH", "SZ") and len(parts[0]) == 6:
        return value
    if market == "HK" and len(parts[0]) == 5:
        return value
    return None


def _simulation_cancel_target(command):
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
        raise CommandError("cancel target is not one exact token-matched order")
    return broker_order_id


def _execute_order_command(command, ContextInfo):
    if (
        TERMINAL_INSTANCE_ID != "guojin_sim"
        or EXECUTION_MODE != "SIMULATION_CALIBRATION"
        or TRADING_ENABLED is not True
        or SIMULATION_ONLY is not True
        or _STATE.account_fingerprint != AUTHORIZED_ACCOUNT_FINGERPRINT
        or _account_type(_STATE.account_type) != "STOCK"
    ):
        raise CommandError("simulation mutation deployment gate is closed")

    payload = command.get("payload")
    if (
        not isinstance(payload, dict)
        or payload.get("simulation_calibration") is not True
        or payload.get("expected_qmt_session_id") != _STATE.session_id
    ):
        raise CommandError("missing current-session simulation authorization")

    command_type = command.get("command_type")
    if command_type == "SUBMIT_LIMIT":
        if _STATE.simulation_submit_calls >= SIMULATION_MAX_SUBMIT_CALLS:
            raise CommandError("simulation submit session limit reached")
        symbol = _simulation_order_symbol(payload.get("symbol"))
        quantity = payload.get("quantity")
        side = payload.get("side")
        try:
            price = float(payload.get("limit_price"))
        except Exception:
            raise CommandError("invalid simulation limit price")
        if symbol is None or side not in ("BUY", "SELL"):
            raise CommandError("simulation calibration requires a supported side and symbol")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
            or quantity > SIMULATION_MAX_ORDER_QUANTITY
        ):
            raise CommandError("simulation calibration quantity exceeds the bounded range")
        if not (price > 0.0 and price <= 100000.0):
            raise CommandError("simulation limit price is outside the safety range")
        passorder(
            23 if side == "BUY" else 24,
            1101,
            _STATE.account_id,
            symbol,
            11,
            price,
            quantity,
            "BIGQMT_SIM_CAL",
            2,
            command.get("broker_token"),
            ContextInfo,
        )
        _STATE.simulation_submit_calls += 1
        return "SIMULATION_SUBMIT_CALL_RETURNED", True

    if command_type == "CANCEL_ORDER":
        if _STATE.simulation_cancel_calls >= SIMULATION_MAX_CANCEL_CALLS:
            raise CommandError("simulation cancel session limit reached")
        broker_order_id = _simulation_cancel_target(command)
        if not can_cancel_order(broker_order_id, _STATE.account_id, _STATE.account_type):
            return "SIMULATION_CANCEL_NOT_CANCELLABLE", False
        result = cancel(broker_order_id, _STATE.account_id, _STATE.account_type, ContextInfo)
        _STATE.simulation_cancel_calls += 1
        if result is True:
            return "SIMULATION_CANCEL_SIGNAL_SENT", True
        return "SIMULATION_CANCEL_NOT_SENT", True

    raise CommandError("unsupported simulation mutation command")
'''

LIVE_CANARY_EXECUTOR = '''_LIVE_CANARY_INSTRUMENT_CANDIDATES = (
    "204001.SH",
    "511880.SH",
    "00700.HK",
    "00700.HGT",
    "00700.SGT",
)
_LIVE_CANARY_MUTATION_SYMBOLS = ("204001.SH", "511880.SH", "00700.HGT")
_LIVE_CANARY_TICK_WINDOW_SECONDS = 10


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


def _tick_state():
    records = getattr(_STATE, "instrument_tick_records", None)
    if not isinstance(records, dict):
        records = {}
        _STATE.instrument_tick_records = records
    return records


def _tick_scalar(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        scalar = value.item()
        if scalar is None or isinstance(scalar, (str, int, float, bool)):
            return scalar
    except Exception:
        pass
    return _text(value)


def _tick_row(data):
    if isinstance(data, dict):
        return data, None
    try:
        if hasattr(data, "iloc") and hasattr(data, "index") and len(data.index) > 0:
            return data.iloc[-1], data.index[-1]
    except Exception:
        return None, None
    return None, None


def _normalize_tick_evidence(symbol, data):
    payload = {
        "requested_symbol": symbol,
        "reported_symbol": None,
        "exact_symbol": False,
        "data_type": type(data).__name__,
    }
    if not isinstance(data, dict):
        payload["error"] = "TICK_CALLBACK_INVALID_RESULT"
        return payload
    if symbol not in data:
        payload["error"] = "TICK_CALLBACK_SYMBOL_MISMATCH"
        try:
            payload["reported_symbols"] = sorted(
                [_text(key) for key in data.keys() if _text(key)]
            )
        except Exception:
            payload["reported_symbols"] = []
        return payload
    frame = data.get(symbol)
    payload["reported_symbol"] = symbol
    payload["data_type"] = type(frame).__name__
    row, tick_index = _tick_row(frame)
    if row is None:
        payload["error"] = "TICK_CALLBACK_EMPTY"
        return payload
    raw_symbol = (
        row.get("stockCode")
        or row.get("stock_code")
        or row.get("code")
        or row.get("InstrumentID")
        if hasattr(row, "get")
        else None
    )
    exchange = (
        row.get("ExchangeID") or row.get("exchangeID") or row.get("market")
        if hasattr(row, "get")
        else None
    )
    tick_time = (
        row.get("time") or row.get("timetag") or row.get("timestamp")
        if hasattr(row, "get")
        else None
    )
    last_price = row.get("lastPrice") if hasattr(row, "get") else None
    if last_price is None and hasattr(row, "get"):
        last_price = row.get("last_price")
    volume = row.get("volume") if hasattr(row, "get") else None
    amount = row.get("amount") if hasattr(row, "get") else None
    payload.update(
        {
            "exact_symbol": True,
            "raw_symbol": _text(_tick_scalar(raw_symbol)),
            "exchange_id": _text(_tick_scalar(exchange)),
            "tick_index": _tick_scalar(tick_index),
            "tick_time": _tick_scalar(tick_time),
            "last_price": _decimal_text(_tick_scalar(last_price)),
            "volume": _decimal_text(_tick_scalar(volume)),
            "amount": _decimal_text(_tick_scalar(amount)),
        }
    )
    return payload


def _tick_capabilities_payload(final=False):
    state = _tick_state()
    candidates = []
    observed_count = 0
    for symbol in _LIVE_CANARY_INSTRUMENT_CANDIDATES:
        record = dict(
            state.get(
                symbol,
                {
                    "symbol": symbol,
                    "subscription_id": None,
                    "accepted": False,
                    "callback_registered": False,
                    "tick_observed": False,
                    "callback_count": 0,
                },
            )
        )
        if record.get("tick_observed"):
            observed_count += 1
        candidates.append(record)
    return {
        "candidates": candidates,
        "observed_count": observed_count,
        "window_seconds": _LIVE_CANARY_TICK_WINDOW_SECONDS,
        "final": bool(final),
    }


def _publish_tick_capabilities(source, final=False):
    payload = _tick_capabilities_payload(final=final)
    _enqueue("instrument_tick_capabilities", source, payload)
    _safe_log("instrument_tick_capabilities", payload)
    flush_transport()
    return payload


def _record_tick_evidence(symbol, data, source="quote_callback"):
    state = _tick_state()
    record = state.setdefault(
        symbol,
        {
            "symbol": symbol,
            "subscription_id": None,
            "accepted": False,
            "callback_registered": True,
            "tick_observed": False,
            "callback_count": 0,
        },
    )
    record["callback_count"] = int(record.get("callback_count") or 0) + 1
    record["last_callback_ms"] = int(time.time() * 1000)
    evidence = _normalize_tick_evidence(symbol, data)
    record["evidence"] = evidence
    first_observed = not record.get("tick_observed") and evidence.get("exact_symbol") is True
    if evidence.get("exact_symbol") is True:
        record["tick_observed"] = True
        record["evidence_source"] = source
    if first_observed or record["callback_count"] == 1:
        _publish_tick_capabilities(source, final=False)


def _tick_callback(symbol):
    def callback(data):
        try:
            _record_tick_evidence(symbol, data)
        except Exception as exc:
            _runtime_error(
                "INSTRUMENT_TICK_CALLBACK_FAILED",
                exc,
                {"symbol": symbol},
            )
    return callback


def _runtime_instrument_subscribe(ContextInfo):
    subscribe = getattr(ContextInfo, "subscribe_quote", None)
    state = _tick_state()
    records = []
    for symbol in _LIVE_CANARY_INSTRUMENT_CANDIDATES:
        record = {
            "symbol": symbol,
            "method": "subscribe_quote",
            "accepted": False,
            "subscription_id": None,
            "callback_registered": False,
            "tick_observed": False,
            "callback_count": 0,
        }
        state[symbol] = dict(record)
        if not callable(subscribe):
            record["error"] = "SUBSCRIBE_QUOTE_UNAVAILABLE"
        else:
            callback = _tick_callback(symbol)
            try:
                subscription_id = subscribe(symbol, "tick", "none", callback=callback)
                record["callback_registered"] = True
            except TypeError:
                try:
                    subscription_id = subscribe(symbol, "tick", callback=callback)
                    record["callback_registered"] = True
                except Exception as exc:
                    subscription_id = None
                    record["error"] = "SUBSCRIBE_QUOTE_CALLBACK_EXCEPTION"
                    record["error_type"] = type(exc).__name__
            except Exception as exc:
                subscription_id = None
                record["error"] = "SUBSCRIBE_QUOTE_CALLBACK_EXCEPTION"
                record["error_type"] = type(exc).__name__
            if isinstance(subscription_id, bool):
                normalized_id = None
            else:
                try:
                    normalized_id = int(subscription_id)
                except Exception:
                    normalized_id = None
            record["subscription_id"] = normalized_id
            record["accepted"] = normalized_id is not None and normalized_id > 0
        # A QMT subscription may invoke its callback synchronously. Preserve
        # any tick evidence written during subscribe_quote instead of
        # overwriting it with the pre-call zero values in ``record``.
        current = state.get(symbol, {})
        current["symbol"] = symbol
        current["method"] = record["method"]
        current["accepted"] = record["accepted"]
        current["subscription_id"] = record["subscription_id"]
        current["callback_registered"] = record["callback_registered"]
        if "error" in record:
            current["error"] = record["error"]
        if "error_type" in record:
            current["error_type"] = record["error_type"]
        state[symbol] = current
        records.append(dict(current))
    _STATE.instrument_probe_attempts = 0
    _STATE.instrument_probe_timer_registered = _register_timer(
        ContextInfo, "instrument_probe_tick", "1nSecond"
    )
    return {
        "candidates": records,
        "probe_timer_registered": _STATE.instrument_probe_timer_registered,
        "max_probe_attempts": _LIVE_CANARY_TICK_WINDOW_SECONDS,
        "tick_evidence_required": True,
    }


def _runtime_full_tick_probe(ContextInfo):
    query = getattr(ContextInfo, "get_full_tick", None)
    result = {"method": "get_full_tick", "attempted": 0, "observed": 0}
    if not callable(query):
        result["error"] = "GET_FULL_TICK_UNAVAILABLE"
        return result
    for symbol in _LIVE_CANARY_INSTRUMENT_CANDIDATES:
        record = _tick_state().get(symbol, {})
        if record.get("tick_observed") is True:
            continue
        result["attempted"] += 1
        try:
            data = query([symbol])
            before = bool(record.get("tick_observed"))
            _record_tick_evidence(symbol, data, source="full_tick_poll")
            after = bool(_tick_state().get(symbol, {}).get("tick_observed"))
            if after and not before:
                result["observed"] += 1
        except Exception as exc:
            current = _tick_state().setdefault(symbol, {"symbol": symbol})
            current["full_tick_error"] = "GET_FULL_TICK_EXCEPTION"
            current["full_tick_error_type"] = type(exc).__name__
    return result


def instrument_probe_tick(ContextInfo):
    attempts = getattr(_STATE, "instrument_probe_attempts", 0)
    if attempts >= _LIVE_CANARY_TICK_WINDOW_SECONDS:
        return
    attempts += 1
    _STATE.instrument_probe_attempts = attempts
    payload = _runtime_instrument_probe(ContextInfo)
    payload["attempt"] = attempts
    payload["max_attempts"] = _LIVE_CANARY_TICK_WINDOW_SECONDS
    observed = any(record.get("observed") for record in payload["candidates"])
    if attempts == 1 or attempts == _LIVE_CANARY_TICK_WINDOW_SECONDS or observed:
        _enqueue("instrument_capabilities", "active_query", payload)
        _safe_log("instrument_capabilities", payload)
        flush_transport()
    payload["full_tick_probe"] = _runtime_full_tick_probe(ContextInfo)
    tick_payload = _tick_capabilities_payload(final=False)
    all_ticks = tick_payload["observed_count"] == len(_LIVE_CANARY_INSTRUMENT_CANDIDATES)
    if attempts == _LIVE_CANARY_TICK_WINDOW_SECONDS or observed or all_ticks:
        _publish_tick_capabilities(
            "probe_window",
            final=(attempts == _LIVE_CANARY_TICK_WINDOW_SECONDS or all_ticks),
        )
    if observed or all_ticks:
        _STATE.instrument_probe_attempts = _LIVE_CANARY_TICK_WINDOW_SECONDS


def _live_canary_symbol(value):
    value = _text(value)
    if value not in _LIVE_CANARY_MUTATION_SYMBOLS:
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
    if symbol == "204001.SH":
        if exchange != "SH" or instrument != "204001":
            raise CommandError("live canary GC001 instrument identity mismatch")
    elif symbol == "511880.SH":
        if exchange != "SH" or instrument != "511880":
            raise CommandError("live canary 511880 instrument identity mismatch")
    elif symbol == "00700.HGT":
        try:
            hsgt_flag = int(details.get("HSGTFlag"))
        except Exception:
            hsgt_flag = None
        if exchange != "HK" or instrument != "00700" or hsgt_flag not in (3, 5):
            raise CommandError("live canary Tencent HGT identity mismatch")
        if "HUGANGTONG" not in _STATE.detected_account_types:
            raise CommandError("live canary Shanghai Stock Connect account unavailable")
    return details


def _live_canary_trade_window_open(symbol):
    now = time.localtime()
    if now.tm_wday >= 5:
        return False
    minutes = now.tm_hour * 60 + now.tm_min
    if symbol == "204001.SH":
        return (570 <= minutes <= 680) or (780 <= minutes <= 920)
    if symbol == "511880.SH":
        return (570 <= minutes <= 680) or (780 <= minutes <= 895)
    return (570 <= minutes <= 710) or (780 <= minutes <= 950)


def _live_canary_cash_preflight():
    query = globals().get("get_trade_detail_data")
    if not callable(query):
        raise CommandError("live canary account query unavailable")
    rows = query(_STATE.account_id, _STATE.account_type, "account")
    if rows is None:
        raise CommandError("live canary account query returned None")
    rows = list(rows)
    if len(rows) != 1:
        raise CommandError("live canary account query is not singular")
    try:
        available_cash = float(_get(rows[0], "m_dAvailable"))
    except Exception:
        raise CommandError("live canary available cash unavailable")
    return available_cash


def _live_canary_tick_price(symbol):
    record = _tick_state().get(symbol)
    if not isinstance(record, dict) or record.get("tick_observed") is not True:
        raise CommandError("live canary exact-symbol tick evidence unavailable")
    evidence = record.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("exact_symbol") is not True:
        raise CommandError("live canary exact-symbol tick evidence invalid")
    try:
        last_price = float(evidence.get("last_price"))
    except Exception:
        raise CommandError("live canary last price unavailable")
    if last_price <= 0.0:
        raise CommandError("live canary last price invalid")
    return last_price


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
    if getattr(_STATE, "live_canary_halted", False):
        raise CommandError("live canary session halted after unknown mutation")

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
        if symbol is None:
            raise CommandError("unsupported live canary symbol")
        if symbol == "204001.SH":
            case_id = "GC001_REJECT"
        elif symbol == "511880.SH":
            case_id = "511880_FUNDS"
        else:
            case_id = "TENCENT_HGT_ROUTE"
        submitted_cases = getattr(_STATE, "live_canary_submitted_cases", set())
        if case_id in submitted_cases:
            raise CommandError("live canary case already submitted")
        if not _live_canary_trade_window_open(symbol):
            raise CommandError("live canary trading window is closed")
        _live_canary_instrument_preflight(ContextInfo, symbol)
        available_cash = _live_canary_cash_preflight()
        if symbol == "204001.SH":
            _live_canary_tick_price(symbol)
            if side != "SELL" or quantity != 10 or price != 100.0:
                raise CommandError("live canary permits GC001 SELL 10 at 100.000")
            if available_cash < 1000.0:
                raise CommandError("live canary requires at least 1000 CNY available cash")
            op_type = 24
        elif symbol == "511880.SH":
            last_price = _live_canary_tick_price(symbol)
            if side != "BUY" or quantity != 100 or not (90.0 <= price <= 110.0):
                raise CommandError("live canary permits 511880 BUY 100 at guarded live price")
            if price < last_price * 0.98 or price > last_price * 1.02:
                raise CommandError("live canary 511880 price is outside exact tick guard")
            if available_cash >= price * quantity * 0.5:
                raise CommandError("live canary 511880 insufficient-funds condition absent")
            op_type = 23
        else:
            if side != "BUY" or quantity != 100 or price != 1.0:
                raise CommandError("live canary permits Tencent HGT BUY 100 at 1.00")
            op_type = 23
        submitted_cases.add(case_id)
        _STATE.live_canary_submitted_cases = submitted_cases
        # Reserve the case and session quota before crossing the broker API
        # boundary. If passorder raises, the outer command handler marks the
        # result UNKNOWN and permanently halts this bridge session.
        _STATE.simulation_submit_calls += 1
        passorder(
            op_type,
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
'''


def rendered(instance_id: str, *, profile: str) -> bytes:
    source = TEMPLATE.read_text(encoding="utf-8")
    if source.count(TOKEN) != 1:
        raise RuntimeError("V05 deployment token must appear exactly once")
    source = source.replace(TOKEN, instance_id)
    if profile == "simulation":
        replacements = {
            'BRIDGE_BUILD = "p4-shadow-command-spool-5"': 'BRIDGE_BUILD = "p5-simulation-calibration-4"',
            'EXECUTION_MODE = "SHADOW"': 'EXECUTION_MODE = "SIMULATION_CALIBRATION"',
            'TRADING_ENABLED = False': 'TRADING_ENABLED = True',
            'LIVE_SUBMIT_ENABLED = False': 'LIVE_SUBMIT_ENABLED = True',
            'LIVE_CANCEL_ENABLED = False': 'LIVE_CANCEL_ENABLED = True',
            'SIMULATION_ONLY = False': 'SIMULATION_ONLY = True',
            'AUTHORIZED_ACCOUNT_FINGERPRINT = None': (
                'AUTHORIZED_ACCOUNT_FINGERPRINT = "' + SIMULATION_FINGERPRINT + '"'
            ),
            'SIMULATION_MAX_ORDER_QUANTITY = 0': 'SIMULATION_MAX_ORDER_QUANTITY = 100',
            'SIMULATION_MAX_SUBMIT_CALLS = 0': 'SIMULATION_MAX_SUBMIT_CALLS = 2000',
            'SIMULATION_MAX_CANCEL_CALLS = 0': 'SIMULATION_MAX_CANCEL_CALLS = 2000',
            'and SIMULATION_MAX_SUBMIT_CALLS == 2': 'and SIMULATION_MAX_SUBMIT_CALLS == 2000',
            'and SIMULATION_MAX_CANCEL_CALLS == 2': 'and SIMULATION_MAX_CANCEL_CALLS == 2000',
            SHADOW_EXECUTOR: SIMULATION_EXECUTOR,
        }
        for before, after in replacements.items():
            if source.count(before) != 1:
                raise RuntimeError("simulation deployment replacement must match exactly once")
            source = source.replace(before, after)
    elif profile == "live_canary":
        replacements = {
            'BRIDGE_BUILD = "p4-shadow-command-spool-5"': 'BRIDGE_BUILD = "p6-guojin-live-canary-5"',
            'EXECUTION_MODE = "SHADOW"': 'EXECUTION_MODE = "LIVE_CANARY"',
            'TRADING_ENABLED = False': 'TRADING_ENABLED = True',
            'LIVE_SUBMIT_ENABLED = False': 'LIVE_SUBMIT_ENABLED = True',
            'LIVE_CANCEL_ENABLED = False': 'LIVE_CANCEL_ENABLED = True',
            'AUTHORIZED_ACCOUNT_FINGERPRINT = None': (
                'AUTHORIZED_ACCOUNT_FINGERPRINT = "' + GUOJIN_LIVE_FINGERPRINT + '"'
            ),
            'SIMULATION_MAX_ORDER_QUANTITY = 0': 'SIMULATION_MAX_ORDER_QUANTITY = 100',
            'SIMULATION_MAX_SUBMIT_CALLS = 0': 'SIMULATION_MAX_SUBMIT_CALLS = 2',
            'SIMULATION_MAX_CANCEL_CALLS = 0': 'SIMULATION_MAX_CANCEL_CALLS = 2',
            'and SIMULATION_MAX_SUBMIT_CALLS == 1': 'and SIMULATION_MAX_SUBMIT_CALLS == 2',
            'and SIMULATION_MAX_CANCEL_CALLS == 1': 'and SIMULATION_MAX_CANCEL_CALLS == 2',
            SHADOW_EXECUTOR: LIVE_CANARY_EXECUTOR,
        }
        for before, after in replacements.items():
            if source.count(before) != 1:
                raise RuntimeError("live canary deployment replacement must match exactly once")
            source = source.replace(before, after)
    elif profile != "shadow":
        raise RuntimeError("unknown deployment profile")
    return source.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build standalone broker-instance V05 scripts")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    for instance_id, (target, profile) in DEPLOYMENTS.items():
        expected = rendered(instance_id, profile=profile)
        if args.check:
            if not target.is_file() or target.read_bytes() != expected:
                stale.append(str(target.relative_to(ROOT)))
        else:
            target.write_bytes(expected)
    if stale:
        raise SystemExit("stale QMT deployment files: " + ", ".join(stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
