import ast
import importlib.util
import json
from pathlib import Path
import time


BRIDGE = Path(__file__).resolve().parents[2] / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_v05", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Obj:
    pass


def account_obj():
    account = Obj()
    account.m_dBalance = 1000.0
    account.m_dAvailable = 900.0
    account.m_dInstrumentValue = 100.0
    account.m_dStockValue = 100.0
    account.m_strStatus = "OK"
    account.m_strTradingDate = "20260915"
    return account


def install_runtime(bridge, tmp_path):
    bridge.account = "SECRET_ACCOUNT"
    bridge.accountType = "STOCK"
    account = account_obj()

    def query(_account_id, _account_type, data_type):
        return {
            "account": [account],
            "position": [],
            "order": [],
            "deal": [],
        }[data_type]

    bridge.get_trade_detail_data = query

    class Context:
        def __init__(self):
            self.timers = []

        def set_account(self, account_id):
            assert account_id == "SECRET_ACCOUNT"

        def run_time(self, callback_name, period, start):
            self.timers.append((callback_name, period, start))

        def is_last_bar(self):
            return True

    context = Context()
    bridge.init(context)
    bridge.after_init(context)
    return context


def write_command(bridge, tmp_path, command):
    body = {
        "command_transport_version": bridge.COMMAND_TRANSPORT_VERSION,
        "command": command,
    }
    path = tmp_path / "commands" / "inbox" / (command["command_id"] + ".json")
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def base_command(bridge, command_id="cmd-001", command_type="SUBMIT_LIMIT"):
    created = int(time.time() * 1000)
    command = {
        "command_protocol_version": bridge.COMMAND_PROTOCOL_VERSION,
        "command_id": command_id,
        "created_ms": created,
        "expires_ms": created + 60_000,
        "account_fingerprint": bridge._STATE.account_fingerprint,
        "command_type": command_type,
        "client_order_id": "cid-001",
        "broker_token": "BQ" + "a" * 20,
        "payload": {"symbol": "000001.SZ", "side": "BUY", "quantity": 100, "limit_price": "10.5"},
    }
    if command_type == "REQUEST_SNAPSHOT":
        command["client_order_id"] = None
        command["broker_token"] = None
        command["payload"] = {}
    return command


def event_frames(tmp_path):
    frames = []
    for path in sorted((tmp_path / "inbox").glob("*.json")):
        frames.append(json.loads(path.read_text(encoding="utf-8"))["event"])
    return frames


def test_v05_is_python36_parseable_and_has_no_broker_mutation_calls():
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


def test_v05_registers_one_second_command_and_five_minute_snapshot_timers(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGQMT_SPOOL_DIR", str(tmp_path))
    bridge = load_bridge()
    context = install_runtime(bridge, tmp_path)

    assert ("command_tick", "1nSecond", bridge.TIMER_START) in context.timers
    assert ("periodic_snapshot_timer", "300nSecond", bridge.TIMER_START) in context.timers
    assert bridge._STATE.command_timer_registered is True
    assert bridge._STATE.snapshot_timer_registered is True
    assert bridge.TRADING_ENABLED is False
    assert bridge.capabilities()["live_submit"] is False
    assert bridge.capabilities()["live_cancel"] is False


def test_v05_shadow_submit_claims_processes_and_emits_result(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGQMT_SPOOL_DIR", str(tmp_path))
    bridge = load_bridge()
    context = install_runtime(bridge, tmp_path)
    command = base_command(bridge)
    write_command(bridge, tmp_path, command)

    bridge.command_tick(context)

    assert not list((tmp_path / "commands" / "inbox").glob("*.json"))
    assert not list((tmp_path / "commands" / "claimed").glob("*.json"))
    assert (tmp_path / "commands" / "processed" / "cmd-001.json").exists()
    results = [event for event in event_frames(tmp_path) if event["event_type"] == "command_result"]
    assert len(results) == 1
    assert results[0]["payload"]["command_id"] == "cmd-001"
    assert results[0]["payload"]["result_status"] == "SHADOW_ACCEPTED"
    assert results[0]["payload"]["live_side_effect"] is False
    assert bridge._STATE.commands_claimed == 1
    assert bridge._STATE.commands_processed == 1


def test_v05_orphaned_claim_is_unknown_and_never_replayed(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGQMT_SPOOL_DIR", str(tmp_path))
    bridge = load_bridge()
    context = install_runtime(bridge, tmp_path)
    command = base_command(bridge, command_id="cmd-orphan")
    inbox_path = write_command(bridge, tmp_path, command)
    claimed_path = tmp_path / "commands" / "claimed" / inbox_path.name
    inbox_path.replace(claimed_path)

    bridge.command_tick(context)

    assert not claimed_path.exists()
    assert (tmp_path / "commands" / "unknown" / "cmd-orphan.json").exists()
    assert not (tmp_path / "commands" / "processed" / "cmd-orphan.json").exists()
    results = [event for event in event_frames(tmp_path) if event["event_type"] == "command_result"]
    orphan = [event for event in results if event["payload"]["command_id"] == "cmd-orphan"]
    assert len(orphan) == 1
    assert orphan[0]["payload"]["result_status"] == "UNKNOWN_ORPHANED"
    assert orphan[0]["payload"]["live_side_effect"] is False


def test_v05_expired_command_is_rejected_without_live_side_effect(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGQMT_SPOOL_DIR", str(tmp_path))
    bridge = load_bridge()
    context = install_runtime(bridge, tmp_path)
    command = base_command(bridge, command_id="cmd-expired")
    command["expires_ms"] = int(time.time() * 1000) - 1
    write_command(bridge, tmp_path, command)

    bridge.command_tick(context)

    assert (tmp_path / "commands" / "rejected" / "cmd-expired.json").exists()
    assert not (tmp_path / "commands" / "processed" / "cmd-expired.json").exists()
    results = [event for event in event_frames(tmp_path) if event["event_type"] == "command_result"]
    expired = [event for event in results if event["payload"]["command_id"] == "cmd-expired"]
    assert len(expired) == 1
    assert expired[0]["payload"]["result_status"] == "REJECTED_EXPIRED"
    assert expired[0]["payload"]["live_side_effect"] is False


def test_v05_snapshot_request_emits_fresh_snapshot_and_result(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGQMT_SPOOL_DIR", str(tmp_path))
    bridge = load_bridge()
    context = install_runtime(bridge, tmp_path)
    command = base_command(bridge, command_id="cmd-snapshot", command_type="REQUEST_SNAPSHOT")
    write_command(bridge, tmp_path, command)
    before = len([event for event in event_frames(tmp_path) if event["event_type"] == "snapshot"])

    bridge.command_tick(context)

    events = event_frames(tmp_path)
    assert len([event for event in events if event["event_type"] == "snapshot"]) == before + 1
    result = [event for event in events if event["event_type"] == "command_result"][-1]
    assert result["payload"]["result_status"] == "SNAPSHOT_EMITTED"
    assert result["payload"]["live_side_effect"] is False
