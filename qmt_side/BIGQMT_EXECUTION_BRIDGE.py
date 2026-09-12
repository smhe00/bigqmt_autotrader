# -*- coding: utf-8 -*-
"""Big QMT-side bridge safety skeleton.

This file intentionally stays compatible with Python 3.6 syntax and standard
library facilities. P0 does not import QMT modules and does not expose a live
submit/cancel path.
"""

PROTOCOL_VERSION = "0.1"
TRADING_ENABLED = False


class BridgeError(RuntimeError):
    code = "E_BRIDGE"


class TradingDisabledError(BridgeError):
    code = "E_TRADING_DISABLED"


def ping():
    return {"ok": True, "protocol_version": PROTOCOL_VERSION}


def capabilities():
    return {
        "protocol_version": PROTOCOL_VERSION,
        "trading_enabled": False,
        "live_submit": False,
        "live_cancel": False,
        "methods": ["ping", "capabilities"],
    }


def submit_limit_order(*args, **kwargs):
    raise TradingDisabledError("P0 safety gate: live order submission is disabled")


def cancel_order(*args, **kwargs):
    raise TradingDisabledError("P0 safety gate: live order cancellation is disabled")
