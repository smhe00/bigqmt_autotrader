import ast
import importlib.util
from pathlib import Path


PROBE = Path(__file__).resolve().parents[2] / "qmt_side" / "BIGQMT_ALL_ACCOUNT_POSITION_PROBE.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("bigqmt_all_account_position_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Position:
    def __init__(self, symbol, exchange, quantity):
        self.m_strInstrumentID = symbol
        self.m_strExchangeID = exchange
        self.m_strInstrumentName = "sample"
        self.m_nVolume = quantity
        self.m_nCanUseVolume = quantity
        self.m_nFrozenVolume = 0
        self.m_nOnRoadVolume = 0
        self.m_dOpenPrice = 10.0
        self.m_dLastPrice = 11.0
        self.m_dMarketValue = quantity * 11.0
        self.m_dPositionCost = quantity * 10.0
        self.m_dPositionProfit = quantity * 1.0


def test_probe_is_python36_parseable_and_contains_no_mutation_calls():
    source = PROBE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PROBE), feature_version=(3, 6))
    forbidden = {
        "passorder",
        "order_lots",
        "order_value",
        "order_target_value",
        "order_target_percent",
        "algo_passorder",
        "smart_algo_passorder",
        "cancel",
        "cancel_task",
        "pause_task",
        "resume_task",
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called.isdisjoint(forbidden)


def test_collect_queries_all_three_account_types_with_same_account_id():
    probe = load_probe()
    calls = []

    def query(account_id, account_type, data_type):
        calls.append((account_id, account_type, data_type))
        return [Position("00700", "HK", len(calls) * 100)]

    payload = probe.collect("SECRET_ACCOUNT", query)
    assert calls == [
        ("SECRET_ACCOUNT", "STOCK", "position"),
        ("SECRET_ACCOUNT", "HUGANGTONG", "position"),
        ("SECRET_ACCOUNT", "SHENGANGTONG", "position"),
    ]
    assert payload["mode"] == "BIGQMT_READ_ONLY"
    assert [item["status"] for item in payload["accounts"]] == ["OK", "OK", "OK"]
    assert [item["positions"][0]["symbol"] for item in payload["accounts"]] == [
        "00700.HK",
        "00700.HK",
        "00700.HK",
    ]
    encoded = repr(payload)
    assert "SECRET_ACCOUNT" not in encoded


def test_none_and_exception_are_not_reported_as_empty_positions():
    probe = load_probe()

    def query(_account_id, account_type, _data_type):
        if account_type == "STOCK":
            return []
        if account_type == "HUGANGTONG":
            return None
        raise RuntimeError("no cache")

    payload = probe.collect("SECRET_ACCOUNT", query)
    stock, hgt, sgt = payload["accounts"]
    assert stock["status"] == "OK"
    assert stock["position_count"] == 0
    assert hgt["status"] == "QUERY_FAILED"
    assert hgt["error_code"] == "POSITION_QUERY_RETURNED_NONE"
    assert sgt["status"] == "QUERY_FAILED"
    assert sgt["error_type"] == "RuntimeError"
