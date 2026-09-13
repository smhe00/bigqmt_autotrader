import ast
import importlib.util
from pathlib import Path

import pytest

from bigqmt_autotrader.qmt import LocalQmtReceiver, QmtIngressBuffer


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V03.py"
FP = "sha256:" + "c" * 64


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_v03", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bridge_v03_is_python36_syntax_compatible_and_has_no_mutation_calls():
    source = BRIDGE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BRIDGE), feature_version=(3, 6))
    called_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)
    assert "passorder" not in called_names
    assert "order_lots" not in called_names
    assert "cancel" not in called_names


def test_bridge_v03_advertises_read_only_loopback_transport():
    bridge = load_bridge()
    caps = bridge.capabilities()
    assert bridge.TRADING_ENABLED is False
    assert bridge.READ_ONLY_ENABLED is True
    assert caps["live_submit"] is False
    assert caps["live_cancel"] is False
    assert caps["transport"] == "loopback_tcp_ack"
    assert caps["transport_host"] == "127.0.0.1"
    assert caps["transport_version"] == "1"

    with pytest.raises(bridge.TradingDisabledError):
        bridge.submit_limit_order("anything")
    with pytest.raises(bridge.TradingDisabledError):
        bridge.cancel_order("anything")


def test_bridge_v03_queue_flushes_to_host_only_after_ack():
    bridge = load_bridge()
    bridge._STATE.account_fingerprint = FP
    bridge._STATE.account_type = "STOCK"
    bridge._enqueue(
        "snapshot",
        "active_query",
        {
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "account": [{"balance": "100.0", "available_cash": "90.0"}],
            "positions": [],
            "orders": [],
            "deals": [],
            "query_errors": [],
        },
    )
    assert len(bridge._STATE.events) == 1

    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    with LocalQmtReceiver(ingress, port=0) as receiver:
        sent = bridge.flush_transport(port=receiver.port)

    assert sent == 1
    assert bridge._STATE.events == []
    assert bridge._STATE.transport_sent == 1
    events = ingress.drain()
    assert len(events) == 1
    assert events[0].event_type == "snapshot"
    assert events[0].payload["account"][0]["balance"] == "100.0"


def test_bridge_v03_failed_transport_retains_fifo():
    bridge = load_bridge()
    bridge._STATE.account_fingerprint = FP
    bridge._STATE.account_type = "STOCK"
    bridge._enqueue(
        "snapshot",
        "active_query",
        {
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "account": [],
            "positions": [],
            "orders": [],
            "deals": [],
            "query_errors": [],
        },
    )
    sent = bridge.flush_transport(port=9)
    assert sent == 0
    assert len(bridge._STATE.events) == 1
    assert bridge._STATE.transport_failures >= 1
