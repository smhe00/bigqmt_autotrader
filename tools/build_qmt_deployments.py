from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05.py"
TOKEN = "__BIGQMT_INSTANCE_ID__"
SIMULATION_FINGERPRINT = "sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702"
DEPLOYMENTS = {
    "galaxy": (ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py", False),
    "guojin": (ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py", False),
    "guojin_sim": (ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py", True),
}

SHADOW_EXECUTOR = '''def _execute_order_command(command, ContextInfo):
    """SHADOW default replaced only in the generated simulation artifact."""
    return "SHADOW_ACCEPTED", False
'''

SIMULATION_EXECUTOR = '''def _simulation_order_symbol(value):
    value = _text(value)
    if not value:
        return None
    parts = value.split(".")
    if len(parts) != 2 or len(parts[0]) != 6 or not parts[0].isdigit():
        return None
    if parts[1] not in ("SH", "SZ"):
        return None
    return value


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


def rendered(instance_id: str, *, simulation_mutation: bool) -> bytes:
    source = TEMPLATE.read_text(encoding="utf-8")
    if source.count(TOKEN) != 1:
        raise RuntimeError("V05 deployment token must appear exactly once")
    source = source.replace(TOKEN, instance_id)
    if simulation_mutation:
        replacements = {
            'BRIDGE_BUILD = "p4-shadow-command-spool-5"': 'BRIDGE_BUILD = "p5-simulation-calibration-3"',
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
    return source.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build standalone broker-instance V05 scripts")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    for instance_id, (target, simulation_mutation) in DEPLOYMENTS.items():
        expected = rendered(instance_id, simulation_mutation=simulation_mutation)
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
