import ast
import importlib.util
from pathlib import Path

import pytest

from bigqmt_autotrader.domain import SystemErrorCode


BRIDGE = Path(__file__).resolve().parents[2] / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_p0", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bridge_source_is_python36_syntax_compatible():
    source = BRIDGE.read_text(encoding="utf-8")
    ast.parse(source, filename=str(BRIDGE), feature_version=(3, 6))


def test_bridge_advertises_no_trading_capability():
    bridge = load_bridge()
    caps = bridge.capabilities()
    assert bridge.TRADING_ENABLED is False
    assert caps["trading_enabled"] is False
    assert caps["live_submit"] is False
    assert caps["live_cancel"] is False
    assert caps["methods"] == ["ping", "capabilities"]


def test_submit_and_cancel_fail_closed():
    bridge = load_bridge()
    assert bridge.TradingDisabledError.code == SystemErrorCode.TRADING_DISABLED.value
    with pytest.raises(bridge.TradingDisabledError):
        bridge.submit_limit_order("anything")
    with pytest.raises(bridge.TradingDisabledError):
        bridge.cancel_order("anything")
