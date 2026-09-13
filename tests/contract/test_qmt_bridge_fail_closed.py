import ast
import importlib.util
from pathlib import Path

import pytest

from bigqmt_autotrader.domain import SystemErrorCode


BRIDGE = Path(__file__).resolve().parents[2] / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE.py"


def load_bridge(**injected_globals):
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_p3", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    for name, value in injected_globals.items():
        setattr(module, name, value)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bridge_source_is_python36_syntax_compatible():
    source = BRIDGE.read_text(encoding="utf-8")
    ast.parse(source, filename=str(BRIDGE), feature_version=(3, 6))


def test_bridge_advertises_read_only_without_trading_capability():
    bridge = load_bridge()
    caps = bridge.capabilities()
    assert bridge.TRADING_ENABLED is False
    assert bridge.READ_ONLY_ENABLED is True
    assert caps["read_only_enabled"] is True
    assert caps["trading_enabled"] is False
    assert caps["live_submit"] is False
    assert caps["live_cancel"] is False
    assert caps["query_types"] == ["ACCOUNT", "POSITION", "ORDER", "DEAL"]
    assert caps["callbacks"] == ["account", "position", "order", "deal"]
    assert caps["methods"] == ["ping", "capabilities", "read_snapshot", "drain_events"]


def test_submit_and_cancel_fail_closed():
    bridge = load_bridge()
    assert bridge.TradingDisabledError.code == SystemErrorCode.TRADING_DISABLED.value
    with pytest.raises(bridge.TradingDisabledError):
        bridge.submit_limit_order("anything")
    with pytest.raises(bridge.TradingDisabledError):
        bridge.cancel_order("anything")


def test_module_load_emits_safe_diagnostic(capsys):
    load_bridge()
    output = capsys.readouterr().out
    assert "BIGQMT_RO_STATUS=" in output
    assert '"status": "module_loaded"' in output
    assert '"account_injected": false' in output
    assert '"query_available": false' in output


def test_top_level_readonly_snapshot_never_logs_raw_account(capsys):
    raw_account = "SECRET_ACCOUNT_123"
    calls = []

    def fake_query(account_id, account_type, data_type):
        calls.append((account_id, account_type, data_type))
        return []

    bridge = load_bridge(
        account=raw_account,
        accountType="STOCK",
        get_trade_detail_data=fake_query,
    )
    output = capsys.readouterr().out

    assert raw_account not in output
    assert '"status": "module_loaded"' in output
    assert '"account_injected": true' in output
    assert '"query_available": true' in output
    assert '"status": "snapshot"' in output
    assert '"status": "top_level_snapshot_ok"' in output
    assert [item[2] for item in calls] == ["account", "position", "order", "deal"]
    assert bridge._STATE.callback_subscription is False
