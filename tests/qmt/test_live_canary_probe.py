from __future__ import annotations

import json

import pytest

from bigqmt_autotrader.qmt.instances import QmtInstance
from bigqmt_autotrader.qmt.live_canary_probe import (
    ACCOUNT_FINGERPRINT,
    BRIDGE_BUILD,
    CONFIRMATION,
    main,
)


@pytest.fixture(autouse=True)
def open_live_canary_window(monkeypatch):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._live_canary_submit_window_open",
        lambda _symbol: True,
    )


def instance(tmp_path) -> QmtInstance:
    return QmtInstance(
        instance_id="guojin",
        root=tmp_path,
        session_id="live-session-01",
        account_fingerprint=ACCOUNT_FINGERPRINT,
        account_type="STOCK",
        bridge_build=BRIDGE_BUILD,
        created_ms=1_700_000_000_000,
        execution_mode="LIVE_CANARY",
        trading_enabled=True,
        live_submit=True,
        live_cancel=True,
        simulation_only=False,
    )


def test_live_probe_requires_exact_confirmation(tmp_path):
    with pytest.raises(SystemExit, match="--confirm must equal"):
        main(["--spool-dir", str(tmp_path), "--confirm", "yes", "submit",
              "--client-order-id", "cid", "--symbol", "204001.SH", "--side", "SELL",
              "--quantity", "10", "--limit-price", "100.000"])


def test_live_probe_publishes_exact_canary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    assert main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
                 "--client-order-id", "cid-live", "--symbol", "204001.SH", "--side", "SELL",
                 "--quantity", "10", "--limit-price", "100.000"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["mode"] == "LIVE_CANARY"
    path = next((tmp_path / "commands" / "inbox").glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))["command"]["payload"]
    assert payload == {
        "symbol": "204001.SH",
        "side": "SELL",
        "quantity": 10,
        "limit_price": "100.000",
        "live_canary": True,
        "expected_qmt_session_id": "live-session-01",
    }


@pytest.mark.parametrize(
    "symbol,side,quantity",
    [("000001.SZ", "SELL", 10), ("204001.SH", "BUY", 10), ("204001.SH", "SELL", 11)],
)
def test_live_probe_rejects_scope_expansion(tmp_path, monkeypatch, symbol, side, quantity):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    with pytest.raises(SystemExit, match="live canary"):
        main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
              "--client-order-id", "cid-live", "--symbol", symbol, "--side", side,
              "--quantity", str(quantity), "--limit-price", "100.000"])
    assert list((tmp_path / "commands" / "inbox").glob("*.json")) == []


def test_live_probe_rejects_non_fixed_gc001_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    with pytest.raises(SystemExit, match="GC001 SELL 10 at 100.000"):
        main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
              "--client-order-id", "cid-live", "--symbol", "204001.SH", "--side", "SELL",
              "--quantity", "10", "--limit-price", "99.995"])


def test_live_probe_publishes_guarded_tencent_funds_case(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    assert main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
                 "--client-order-id", "cid-tencent-funds", "--symbol", "00700.SGT",
                 "--side", "BUY", "--quantity", "100", "--limit-price", "600.00"]) == 0
    capsys.readouterr()
    path = next((tmp_path / "commands" / "inbox").glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))["command"]["payload"]
    assert payload["symbol"] == "00700.SGT"
    assert payload["side"] == "BUY"
    assert payload["quantity"] == 100
    assert payload["limit_price"] == "600.00"
