import ast
import importlib.util
import json
from pathlib import Path


BRIDGE = Path(__file__).resolve().parents[2] / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_read_only", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Obj:
    pass


def make_rows():
    account = Obj()
    account.m_dBalance = 1000.5
    account.m_dAvailable = 800.25
    account.m_dInstrumentValue = 200.25
    account.m_dStockValue = 200.25
    account.m_strStatus = "OK"
    account.m_strTradingDate = "20260913"
    account.m_strAccountID = "RAW_ACCOUNT_SHOULD_NOT_ESCAPE"

    position = Obj()
    position.m_strInstrumentID = "000001"
    position.m_strExchangeID = "SZ"
    position.m_nVolume = 100
    position.m_nCanUseVolume = 80
    position.m_nFrozenVolume = 20
    position.m_nOnRoadVolume = 0
    position.m_dMarketValue = 1200.0
    position.m_dLastPrice = 12.0
    position.m_dOpenPrice = 10.0
    position.m_strTradingDay = "20260913"
    position.m_strAccountID = "RAW_ACCOUNT_SHOULD_NOT_ESCAPE"

    order = Obj()
    order.m_strInstrumentID = "000001"
    order.m_strExchangeID = "SZ"
    order.m_strOrderRef = "local-ref"
    order.m_strOrderSysID = "broker-order"
    order.m_strRemark = "cid-token"
    order.m_nOrderStatus = 56
    order.m_nOrderSubmitStatus = 0
    order.m_nVolumeTotalOriginal = 100
    order.m_nVolumeTraded = 50
    order.m_nVolumeTotal = 50
    order.m_dCancelAmount = 0
    order.m_dLimitPrice = 12.1
    order.m_dTradedPrice = 12.0
    order.m_strInsertDate = "20260913"
    order.m_strInsertTime = "100000"
    order.m_nErrorID = 0
    order.m_strCancelInfo = ""
    order.m_strOptName = "BUY"
    order.m_strAccountID = "RAW_ACCOUNT_SHOULD_NOT_ESCAPE"

    deal = Obj()
    deal.m_strInstrumentID = "000001"
    deal.m_strExchangeID = "SZ"
    deal.m_strTradeID = "trade-1"
    deal.m_strOrderRef = "local-ref"
    deal.m_strOrderSysID = "broker-order"
    deal.m_strRemark = "cid-token"
    deal.m_dPrice = 12.0
    deal.m_nVolume = 50
    deal.m_strTradeDate = "20260913"
    deal.m_strTradeTime = "100001"
    deal.m_dCommission = 0.3
    deal.m_dTradeAmount = 600.0
    deal.m_strOptName = "BUY"
    deal.m_strAccountID = "RAW_ACCOUNT_SHOULD_NOT_ESCAPE"

    return account, position, order, deal


def test_source_has_no_broker_mutation_call_surface():
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
    assert "threading" not in imports
    assert "multiprocessing" not in imports
    assert "subprocess" not in imports


def test_snapshot_normalization_is_read_only_and_hides_raw_account():
    bridge = load_bridge()
    account, position, order, deal = make_rows()

    def query(account_id, account_type, data_type):
        assert account_id == "SECRET_ACCOUNT"
        assert account_type == "STOCK"
        return {
            "account": [account],
            "position": [position],
            "order": [order],
            "deal": [deal],
        }[data_type]

    snapshot = bridge.read_snapshot(
        account_id="SECRET_ACCOUNT",
        account_type="STOCK",
        query_fn=query,
        emit=False,
    )

    serialized = json.dumps(snapshot, ensure_ascii=True, sort_keys=True)
    assert "SECRET_ACCOUNT" not in serialized
    assert "RAW_ACCOUNT_SHOULD_NOT_ESCAPE" not in serialized
    assert snapshot["account_fingerprint"].startswith("sha256:")
    assert snapshot["account"][0]["available_cash"] == "800.25"
    assert snapshot["positions"][0]["symbol"] == "000001.SZ"
    assert snapshot["positions"][0]["sellable_quantity"] == 80
    assert snapshot["orders"][0]["filled_quantity"] == 50
    assert snapshot["orders"][0]["remark"] == "cid-token"
    assert snapshot["deals"][0]["trade_id"] == "trade-1"


def test_snapshot_query_failure_is_fail_visible_without_exception_text():
    bridge = load_bridge()

    def query(account_id, account_type, data_type):
        if data_type == "order":
            raise RuntimeError("sensitive local path C:/qmt/userdata")
        return []

    snapshot = bridge.read_snapshot(
        account_id="SECRET_ACCOUNT",
        account_type="STOCK",
        query_fn=query,
        emit=False,
    )

    assert snapshot["query_errors"] == [
        {"data_type": "ORDER", "error_type": "RuntimeError"}
    ]
    assert "sensitive local path" not in json.dumps(snapshot)


def test_qmt_lifecycle_binds_injected_account_and_queues_safe_snapshot(capsys):
    bridge = load_bridge()
    account, position, order, deal = make_rows()
    bridge.account = "SECRET_ACCOUNT"
    bridge.accountType = "STOCK"

    def query(account_id, account_type, data_type):
        return {
            "account": [account],
            "position": [position],
            "order": [order],
            "deal": [deal],
        }[data_type]

    bridge.get_trade_detail_data = query

    class Context:
        def __init__(self):
            self.bound = []

        def set_account(self, account_id):
            self.bound.append(account_id)

        def is_last_bar(self):
            return True

    context = Context()
    bridge.init(context)
    bridge.after_init(context)

    assert context.bound == ["SECRET_ACCOUNT"]
    events = bridge.drain_events()
    assert [event["event_type"] for event in events] == ["bridge_ready", "snapshot"]
    serialized = json.dumps(events, ensure_ascii=True)
    assert "SECRET_ACCOUNT" not in serialized
    assert "RAW_ACCOUNT_SHOULD_NOT_ESCAPE" not in serialized

    out = capsys.readouterr().out
    assert "BIGQMT_RO_STATUS=" in out
    assert "SECRET_ACCOUNT" not in out
    assert "800.25" not in out


def test_callbacks_queue_normalized_facts_without_raw_account(capsys):
    bridge = load_bridge()
    _, position, order, deal = make_rows()

    bridge.position_callback(None, position)
    bridge.order_callback(None, order)
    bridge.deal_callback(None, deal)

    events = bridge.drain_events()
    assert [event["event_type"] for event in events] == ["position", "order", "deal"]
    serialized = json.dumps(events, ensure_ascii=True)
    assert "RAW_ACCOUNT_SHOULD_NOT_ESCAPE" not in serialized
    assert events[1]["payload"]["broker_order_id"] == "broker-order"
    assert events[2]["payload"]["remark"] == "cid-token"

    out = capsys.readouterr().out
    assert "BIGQMT_RO_STATUS=" in out
    assert "broker-order" not in out
    assert "cid-token" not in out
