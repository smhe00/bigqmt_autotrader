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

LIVE_CANARY_EXECUTOR = '''def _runtime_instrument_probe(ContextInfo):
    candidates = ("00700.HK", "00700.HGT", "00700.SGT")
    query = None
    method = None
    for name in ("get_instrument_detail", "get_instrumentdetail"):
        candidate = getattr(ContextInfo, name, None)
        if callable(candidate):
            query = candidate
            method = name
            break
    records = []
    for symbol in candidates:
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
            'BRIDGE_BUILD = "p4-shadow-command-spool-5"': 'BRIDGE_BUILD = "p6-guojin-live-canary-3"',
            'EXECUTION_MODE = "SHADOW"': 'EXECUTION_MODE = "LIVE_CANARY"',
            'TRADING_ENABLED = False': 'TRADING_ENABLED = True',
            'LIVE_SUBMIT_ENABLED = False': 'LIVE_SUBMIT_ENABLED = True',
            'LIVE_CANCEL_ENABLED = False': 'LIVE_CANCEL_ENABLED = True',
            'AUTHORIZED_ACCOUNT_FINGERPRINT = None': (
                'AUTHORIZED_ACCOUNT_FINGERPRINT = "' + GUOJIN_LIVE_FINGERPRINT + '"'
            ),
            'SIMULATION_MAX_ORDER_QUANTITY = 0': 'SIMULATION_MAX_ORDER_QUANTITY = 100',
            'SIMULATION_MAX_SUBMIT_CALLS = 0': 'SIMULATION_MAX_SUBMIT_CALLS = 1',
            'SIMULATION_MAX_CANCEL_CALLS = 0': 'SIMULATION_MAX_CANCEL_CALLS = 1',
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
