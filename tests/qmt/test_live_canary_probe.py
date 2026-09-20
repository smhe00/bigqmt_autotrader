from __future__ import annotations

import json

import pytest

from bigqmt_autotrader.qmt.instances import QmtInstance
from bigqmt_autotrader.qmt.live_canary_probe import (
    ACCOUNT_FINGERPRINT,
    AUTHORIZED_CASE_TEXT,
    BRIDGE_BUILD,
    CONFIRMATION,
    main,
)


@pytest.fixture(autouse=True)
def open_live_canary_window(monkeypatch):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._live_canary_submit_window_open",
        lambda: True,
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
              "--client-order-id", "cid", "--symbol", "00700.HGT", "--side", "BUY",
              "--quantity", "100", "--limit-price", "1.00"])


def test_live_probe_publishes_exact_hgt_case(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    assert main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
                 "--client-order-id", "cid-hgt", "--symbol", "00700.HGT", "--side", "BUY",
                 "--quantity", "100", "--limit-price", "1.00"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["mode"] == "LIVE_CANARY"
    path = next((tmp_path / "commands" / "inbox").glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))["command"]["payload"]
    assert payload == {
        "symbol": "00700.HGT",
        "side": "BUY",
        "quantity": 100,
        "limit_price": "1.00",
        "live_canary": True,
        "expected_qmt_session_id": "live-session-01",
    }


@pytest.mark.parametrize(
    "symbol,side,quantity,price",
    [
        # GC001 calibration is complete: never resubmittable in this build.
        ("204001.SH", "SELL", 10, "100.000"),
        # 511880 stays a read-only diagnostic pending a separate Gate.
        ("511880.SH", "BUY", 100, "100.805"),
        ("000001.SZ", "BUY", 100, "1.00"),
        ("00700.HK", "BUY", 100, "1.00"),
        ("00700.SGT", "BUY", 100, "1.00"),
        # HGT route with any other shape is not authorized.
        ("00700.HGT", "SELL", 100, "1.00"),
        ("00700.HGT", "BUY", 200, "1.00"),
        ("00700.HGT", "BUY", 100, "1.01"),
        ("00700.HGT", "BUY", 100, "0.99"),
    ],
)
def test_live_probe_rejects_every_other_case_before_spool(
    tmp_path, monkeypatch, symbol, side, quantity, price
):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    with pytest.raises(SystemExit, match="exactly one submit case"):
        main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
              "--client-order-id", "cid-reject", "--symbol", symbol, "--side", side,
              "--quantity", str(quantity), "--limit-price", price])
    inbox = tmp_path / "commands" / "inbox"
    assert not inbox.exists() or list(inbox.glob("*.json")) == []


def test_live_probe_rejects_non_finite_price(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    with pytest.raises(SystemExit, match="decimal text|finite"):
        main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
              "--client-order-id", "cid-nan", "--symbol", "00700.HGT", "--side", "BUY",
              "--quantity", "100", "--limit-price", "NaN"])


def test_live_probe_rejects_when_trading_window_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe._live_canary_submit_window_open",
        lambda: False,
    )
    with pytest.raises(SystemExit, match="trading window is closed"):
        main(["--spool-dir", str(tmp_path), "--confirm", CONFIRMATION, "submit",
              "--client-order-id", "cid-closed", "--symbol", "00700.HGT", "--side", "BUY",
              "--quantity", "100", "--limit-price", "1.00"])
    inbox = tmp_path / "commands" / "inbox"
    assert not inbox.exists() or list(inbox.glob("*.json")) == []


def test_live_probe_rejects_old_build_instance(tmp_path, monkeypatch):
    # The pinned loader must reject a build-6 instance so an old running
    # bridge can never receive build-7 commands.
    old = QmtInstance(
        instance_id="guojin",
        root=tmp_path,
        session_id="live-session-01",
        account_fingerprint=ACCOUNT_FINGERPRINT,
        account_type="STOCK",
        bridge_build="p6-guojin-live-canary-6",
        created_ms=1_700_000_000_000,
        execution_mode="LIVE_CANARY",
        trading_enabled=True,
        live_submit=True,
        live_cancel=True,
        simulation_only=False,
    )
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.live_canary_probe.load_instance",
        lambda *args, **kwargs: old,
    )
    with pytest.raises(SystemExit, match="pinned Guojin live canary"):
        main(["--spool-dir", str(tmp_path / "guojin"), "--confirm", CONFIRMATION,
              "submit", "--client-order-id", "cid-old", "--symbol", "00700.HGT",
              "--side", "BUY", "--quantity", "100", "--limit-price", "1.00"])


def test_authorized_case_text_is_single_hgt_case():
    assert AUTHORIZED_CASE_TEXT == "00700.HGT BUY 100 @ 1.00 HKD"
    assert BRIDGE_BUILD == "p6-guojin-live-canary-7"
