from __future__ import annotations

import json

import pytest

from bigqmt_autotrader.qmt.instances import QmtInstance
from bigqmt_autotrader.qmt.simulation_probe import CONFIRMATION, main


FINGERPRINT = "sha256:" + "a" * 64


def instance(tmp_path) -> QmtInstance:
    return QmtInstance(
        instance_id="sim_01",
        root=tmp_path,
        session_id="session-01",
        account_fingerprint=FINGERPRINT,
        account_type="STOCK",
        bridge_build="p5-simulation-calibration-2",
        created_ms=1_700_000_000_000,
        execution_mode="SIMULATION_CALIBRATION",
        trading_enabled=True,
        live_submit=True,
        live_cancel=True,
        simulation_only=True,
    )


def test_simulation_probe_requires_exact_confirmation(tmp_path):
    with pytest.raises(SystemExit, match="--confirm must equal"):
        main(
            [
                "--spool-dir",
                str(tmp_path),
                "--confirm",
                "yes",
                "submit",
                "--client-order-id",
                "cid-001",
                "--symbol",
                "000001.SZ",
                "--quantity",
                "100",
                "--limit-price",
                "10.00",
            ]
        )


def test_simulation_probe_publishes_current_session_bounded_submit(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.simulation_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )

    result = main(
        [
            "--spool-dir",
            str(tmp_path),
            "--confirm",
            CONFIRMATION,
            "submit",
            "--client-order-id",
            "cid-001",
            "--symbol",
            "000001.SZ",
            "--quantity",
            "100",
            "--limit-price",
            "10.00",
        ]
    )

    assert result == 0
    status = json.loads(capsys.readouterr().out)
    assert status["mode"] == "SIMULATION_CALIBRATION"
    assert status["live_side_effect_authorized"] is True
    paths = list((tmp_path / "commands" / "inbox").glob("*.json"))
    assert len(paths) == 1
    command = json.loads(paths[0].read_text(encoding="utf-8"))["command"]
    assert command["payload"]["simulation_calibration"] is True
    assert command["payload"]["expected_qmt_session_id"] == "session-01"
    assert command["payload"]["quantity"] == 100


def test_simulation_probe_rejects_more_than_100_shares(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.simulation_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    with pytest.raises(SystemExit, match="exactly 100"):
        main(
            [
                "--spool-dir",
                str(tmp_path),
                "--confirm",
                CONFIRMATION,
                "submit",
                "--client-order-id",
                "cid-001",
                "--symbol",
                "000001.SZ",
                "--quantity",
                "200",
                "--limit-price",
                "10.00",
            ]
        )


def test_simulation_probe_never_republishes_same_cancel_target(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        "bigqmt_autotrader.qmt.simulation_probe._load_authorized_instance",
        lambda _path: instance(tmp_path),
    )
    arguments = [
        "--spool-dir",
        str(tmp_path),
        "--confirm",
        CONFIRMATION,
        "cancel",
        "--client-order-id",
        "cid-001",
        "--broker-order-id",
        "broker-001",
    ]

    assert main(arguments) == 0
    first_status = json.loads(capsys.readouterr().out)
    assert first_status["command_id"].startswith("simcancel-")

    with pytest.raises(SystemExit, match="cancel already published"):
        main(arguments)

    assert len(list((tmp_path / "commands" / "inbox").glob("*.json"))) == 1
