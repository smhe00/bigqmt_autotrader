import ast
import importlib.util
import json
from pathlib import Path


BRIDGE = Path(__file__).resolve().parents[2] / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V04.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_v04", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Obj:
    pass


def test_v04_is_python36_parseable_has_no_socket_or_mutation_calls():
    source = BRIDGE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BRIDGE), feature_version=(3, 6))
    forbidden_calls = {
        "passorder",
        "order_lots",
        "cancel",
        "algo_passorder",
        "smart_algo_passorder",
        "cancel_task",
        "pause_task",
        "resume_task",
    }
    calls = set()
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert not (calls & forbidden_calls)
    assert "socket" not in imports
    assert "threading" not in imports
    assert "multiprocessing" not in imports
    assert "subprocess" not in imports


def test_v04_atomically_spools_bridge_ready_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGQMT_SPOOL_DIR", str(tmp_path))
    bridge = load_bridge()
    bridge.account = "SECRET_ACCOUNT"
    bridge.accountType = "STOCK"

    account = Obj()
    account.m_dBalance = 1000.0
    account.m_dAvailable = 900.0
    account.m_dInstrumentValue = 100.0
    account.m_dStockValue = 100.0
    account.m_strStatus = "OK"
    account.m_strTradingDate = "20260914"

    position = Obj()
    position.m_strInstrumentID = "000001"
    position.m_strExchangeID = "SZ"
    position.m_nVolume = 100
    position.m_nCanUseVolume = 100

    def query(account_id, account_type, data_type):
        assert account_id == "SECRET_ACCOUNT"
        assert account_type == "STOCK"
        return {
            "account": [account],
            "position": [position],
            "order": [],
            "deal": [],
        }[data_type]

    bridge.get_trade_detail_data = query

    class Context:
        def set_account(self, account_id):
            assert account_id == "SECRET_ACCOUNT"

        def is_last_bar(self):
            return True

    context = Context()
    bridge.init(context)
    bridge.after_init(context)

    inbox = tmp_path / "inbox"
    files = sorted(inbox.glob("*.json"))
    assert len(files) == 2
    assert not list(inbox.glob("*.tmp-*"))
    frames = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    events = [frame["event"] for frame in frames]
    assert [event["event_type"] for event in events] == ["bridge_ready", "snapshot"]
    assert all(frame["transport_version"] == "1" for frame in frames)
    assert all("SECRET_ACCOUNT" not in path.read_text(encoding="utf-8") for path in files)
    assert bridge._STATE.transport_persisted == 2
    assert bridge._STATE.transport_failures == 0
    assert bridge.drain_events() == []


def test_v04_keeps_event_in_memory_if_spool_publish_fails(monkeypatch):
    bridge = load_bridge()
    bridge._STATE.account_fingerprint = "sha256:" + "a" * 64
    bridge._STATE.account_type = "STOCK"
    bridge._enqueue("bridge_ready", "init", {"ok": True})

    def fail(_event):
        raise OSError("disk unavailable")

    monkeypatch.setattr(bridge, "_persist_event", fail)
    assert bridge.flush_transport() == 0
    assert len(bridge._STATE.events) == 1
    assert bridge._STATE.transport_failures == 1
    assert bridge._STATE.last_transport_error_type == "OSError"
