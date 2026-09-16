from __future__ import annotations

import json

from bigqmt_autotrader.qmt.shadow_probe import main


ACCOUNT_FINGERPRINT = "sha256:" + "a" * 64


def test_shadow_probe_publishes_cancel_without_live_side_effect(tmp_path, capsys):
    result = main(
        [
            "--spool-dir",
            str(tmp_path),
            "--account-fingerprint",
            ACCOUNT_FINGERPRINT,
            "cancel",
            "--client-order-id",
            "cid-cancel-001",
            "--broker-order-id",
            "shadow-order-001",
        ]
    )

    assert result == 0
    status = json.loads(capsys.readouterr().out)
    assert status["command_type"] == "CANCEL_ORDER"
    assert status["live_side_effect"] is False

    paths = list((tmp_path / "commands" / "inbox").glob("*.json"))
    assert len(paths) == 1
    command = json.loads(paths[0].read_text(encoding="utf-8"))["command"]
    assert command["command_type"] == "CANCEL_ORDER"
    assert command["client_order_id"] == "cid-cancel-001"
    assert command["payload"] == {"broker_order_id": "shadow-order-001"}
