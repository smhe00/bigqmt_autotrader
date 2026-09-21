from __future__ import annotations

import importlib.util
from pathlib import Path


BRIDGE = Path(__file__).resolve().parents[2] / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("bigqmt_bridge_linked_query", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Obj:
    pass


def test_linked_hgt_sgt_order_deal_queries_preserve_explicit_route_identity():
    bridge = load_bridge()
    bridge._STATE.detected_account_types.update(
        {"STOCK", "HUGANGTONG", "SHENGANGTONG"}
    )
    calls = []

    order = Obj()
    order.m_strInstrumentID = "00700"
    order.m_strExchangeID = "HGT"
    order.m_strOrderSysID = "hgt-order"
    order.m_strRemark = "BQ" + "1" * 20
    order.m_nOrderStatus = 50
    order.m_nOrderSubmitStatus = 51
    order.m_nVolumeTotalOriginal = 100
    order.m_nVolumeTraded = 0
    order.m_nVolumeTotal = 100

    deal = Obj()
    deal.m_strInstrumentID = "00700"
    deal.m_strExchangeID = "SGT"
    deal.m_strOrderSysID = "sgt-order"
    deal.m_strTradeID = "sgt-trade"
    deal.m_strRemark = "BQ" + "2" * 20
    deal.m_nVolume = 100
    deal.m_dPrice = 400.0

    def query(account_id, account_type, data_type):
        calls.append((account_id, account_type, data_type))
        if account_type == "HUGANGTONG" and data_type == "order":
            return [order]
        if account_type == "SHENGANGTONG" and data_type == "deal":
            return [deal]
        return []

    snapshot = bridge.read_snapshot(
        account_id="SECRET_ACCOUNT",
        account_type="STOCK",
        query_fn=query,
        emit=False,
    )

    assert ("SECRET_ACCOUNT", "HUGANGTONG", "order") in calls
    assert ("SECRET_ACCOUNT", "HUGANGTONG", "deal") in calls
    assert ("SECRET_ACCOUNT", "SHENGANGTONG", "order") in calls
    assert ("SECRET_ACCOUNT", "SHENGANGTONG", "deal") in calls
    assert snapshot["orders"][0]["route_account_type"] == "HUGANGTONG"
    assert snapshot["orders"][0]["route_account_fingerprint"].startswith("sha256:")
    assert snapshot["deals"][0]["route_account_type"] == "SHENGANGTONG"
    assert snapshot["deals"][0]["route_account_fingerprint"].startswith("sha256:")
    assert "SECRET_ACCOUNT" not in repr(snapshot)
