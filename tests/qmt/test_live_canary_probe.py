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
              "--client-order-id", "cid", "--symbol", "00700.SGT", "--side", "BUY",
              "--quantity", "100", "--limit-price", "1.00"])


def test_live_probe_publishes_exact_canary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    assert main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
                 "--client-order-id", "cid-live", "--symbol", "00700.SGT", "--side", "BUY",
                 "--quantity", "100", "--limit-price", "1.00"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["mode"] == "LIVE_CANARY"
    path = next((tmp_path / "commands" / "inbox").glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))["command"]["payload"]
    assert payload == {
        "symbol": "00700.SGT",
        "side": "BUY",
        "quantity": 100,
        "limit_price": "1.00",
        "live_canary": True,
        "expected_qmt_session_id": "live-session-01",
    }


@pytest.mark.parametrize(
    "symbol,side,quantity",
    [("000001.SZ", "BUY", 100), ("00700.SGT", "SELL", 100), ("00700.SGT", "BUY", 99)],
)
def test_live_probe_rejects_scope_expansion(tmp_path, monkeypatch, symbol, side, quantity):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    with pytest.raises(SystemExit, match="permits only"):
        main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
              "--client-order-id", "cid-live", "--symbol", symbol, "--side", side,
              "--quantity", str(quantity), "--limit-price", "1.00"])
    assert list((tmp_path / "commands" / "inbox").glob("*.json")) == []


def test_live_probe_rejects_price_above_fixed_canary_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    with pytest.raises(SystemExit, match="must equal 1.00"):
        main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
              "--client-order-id", "cid-live", "--symbol", "00700.SGT", "--side", "BUY",
              "--quantity", "100", "--limit-price", "1.01"])
