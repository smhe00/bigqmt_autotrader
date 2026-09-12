import importlib.util
from pathlib import Path

import pytest


BRIDGE = Path(__file__).resolve().parents[2] / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_p0", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bridge_advertises_no_trading_capability():
    bridge = load_bridge()
    caps = bridge.capabilities()
    assert bridge.TRADING_ENABLED is False
    assert caps["trading_enabled"] is False
    assert caps["live_submit"] is False
    assert caps["live_cancel"] is False


def test_submit_and_cancel_fail_closed():
    bridge = load_bridge()
    with pytest.raises(bridge.TradingDisabledError):
        bridge.submit_limit_order("anything")
    with pytest.raises(bridge.TradingDisabledError):
        bridge.cancel_order("anything")
