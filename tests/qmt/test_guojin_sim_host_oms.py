from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from bigqmt_autotrader.domain import OrderStatus
from bigqmt_autotrader.oms.repository import QmtDurableIdentityConflict
from bigqmt_autotrader.qmt.commands import QmtCommandSpool
from bigqmt_autotrader.qmt.guojin_sim_oms import (
    GuojinSimOmsRuntime,
    guojin_sim_oms_authorized,
)
from bigqmt_autotrader.qmt.host import _build_ingestion
from bigqmt_autotrader.qmt.instances import QmtInstance
from bigqmt_autotrader.qmt.protocol import QmtEvent


FP = "sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702"
SESSION = "guojin-sim-session-p6t003"


def instance(root: Path, **overrides) -> QmtInstance:
    values = dict(
        instance_id="guojin_sim",
        root=root,
        session_id=SESSION,
        account_fingerprint=FP,
        account_type="STOCK",
        bridge_build="p5-simulation-calibration-7",
        created_ms=1_800_000_000_000,
        execution_mode="SIMULATION_CALIBRATION",
        trading_enabled=True,
        live_submit=True,
        live_cancel=True,
        simulation_only=True,
    )
    values.update(overrides)
    return QmtInstance(**values)


def durable_submit(
    root: Path,
    *,
    client_order_id: str,
    command_id: str,
    symbol: str = "510300.SH",
    state: str = "processed",
) -> str:
    spool = QmtCommandSpool(root)
    command = spool.publish_submit(
        account_fingerprint=FP,
        client_order_id=client_order_id,
        symbol=symbol,
        side="BUY",
        quantity=100,
        limit_price="1.00",
        created_ms=1_800_000_000_000,
        expires_ms=1_800_000_060_000,
        command_id=command_id,
        simulation_calibration=True,
        expected_qmt_session_id=SESSION,
    )
    (root / "commands" / "inbox" / (command_id + ".json")).replace(
        root / "commands" / state / (command_id + ".json")
    )
    assert command.broker_token is not None
    return command.broker_token


def event(sequence: int, event_type: str, payload: dict, *, source: str = "callback") -> QmtEvent:
    return QmtEvent.from_mapping(
        {
            "protocol_version": "0.2",
            "session_id": SESSION,
            "sequence": sequence,
            "timestamp_ms": 1_800_000_000_000 + sequence,
            "event_type": event_type,
            "source": source,
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "terminal_instance_id": "guojin_sim",
            "payload": payload,
        }
    )


def order_payload(token: str, status: int, *, broker_id: str = "9001") -> dict:
    filled = 100 if status == 56 else 0
    return {
        "symbol": "510300.SH",
        "remark": token,
        "order_ref": "ref-1",
        "broker_order_id": "" if status == 57 else broker_id,
        "status_code": status,
        "submit_status_code": 51,
        "original_quantity": 100,
        "filled_quantity": filled,
        "remaining_quantity": 0 if status == 56 else 100,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"instance_id": "guojin"},
        {"instance_id": "galaxy"},
        {"execution_mode": "SHADOW", "trading_enabled": False,
         "live_submit": False, "live_cancel": False, "simulation_only": False},
        {"simulation_only": False},
        {"bridge_build": "untrusted-build"},
        {"account_fingerprint": "sha256:" + "a" * 64},
    ],
)
def test_mapper_sink_only_enabled_for_exact_authorized_guojin_sim(tmp_path, overrides):
    candidate = instance(tmp_path, **overrides)
    ingestion, runtime = _build_ingestion(
        candidate, allow_simulation_mutation=True
    )
    assert runtime is None
    assert ingestion.evidence_mapper is None
    assert not (tmp_path / "host_oms.sqlite3").exists()


def test_explicit_flag_is_required(tmp_path):
    assert guojin_sim_oms_authorized(
        instance(tmp_path), allow_simulation_mutation=False
    ) is False


def test_exact_authorized_instance_enables_mapper_and_persistent_sink(tmp_path):
    ingestion, runtime = _build_ingestion(
        instance(tmp_path), allow_simulation_mutation=True
    )
    assert runtime is not None
    assert ingestion.evidence_sink is runtime
    assert ingestion.evidence_mapper is runtime.mapper
    assert ingestion.snapshot_evidence_mapper == runtime.mapper.map_snapshot
    assert (tmp_path / "host_oms.sqlite3").exists()
    runtime.close()


def test_durable_identity_and_unknown_recover_without_retry(tmp_path):
    durable_submit(
        tmp_path, client_order_id="cid-unknown", command_id="cmd-unknown", state="unknown"
    )
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    assert runtime.repository.get_status(FP, "cid-unknown") is OrderStatus.RECONCILING
    assert (tmp_path / "commands" / "unknown" / "cmd-unknown.json").exists()
    runtime.close()

    restarted = GuojinSimOmsRuntime(instance(tmp_path))
    assert restarted.refresh_identities() == 0
    assert restarted.repository.get_status(FP, "cid-unknown") is OrderStatus.RECONCILING
    assert len(restarted.repository.list_events(FP, "cid-unknown")) == 1
    restarted.close()


def test_qmt_session_rollover_restores_trusted_oms_identity_without_command_replay(tmp_path):
    token = durable_submit(
        tmp_path, client_order_id="cid-prior-session", command_id="cmd-prior-session"
    )
    first = GuojinSimOmsRuntime(instance(tmp_path))
    evidence = first.mapper(event(1, "order", order_payload(token, 54)))
    assert evidence is not None
    first.ingest_broker_evidence(evidence)
    first.close()

    restarted = GuojinSimOmsRuntime(instance(tmp_path, session_id="next-qmt-session"))
    assert restarted.refresh_identities() == 0
    assert restarted.restore_persisted_identities() == 1
    assert restarted.repository.get_status(FP, "cid-prior-session") is OrderStatus.CANCELLED
    from dataclasses import replace

    later = replace(event(2, "order", order_payload(token, 54)), session_id="next-qmt-session")
    mapped = restarted.mapper(later)
    assert mapped is not None
    assert restarted.ingest_broker_evidence(mapped).duplicate is True
    assert len(restarted.repository.list_events(FP, "cid-prior-session")) == 2
    restarted.close()


def test_conflicting_durable_identity_fails_closed(tmp_path):
    durable_submit(tmp_path, client_order_id="cid-conflict", command_id="cmd-a")
    durable_submit(
        tmp_path,
        client_order_id="cid-conflict",
        command_id="cmd-b",
        symbol="511880.SH",
    )
    with pytest.raises((ValueError, QmtDurableIdentityConflict), match="conflict"):
        GuojinSimOmsRuntime(instance(tmp_path))
    conn = sqlite3.connect(tmp_path / "host_oms.sqlite3")
    assert conn.execute("SELECT COUNT(*) FROM qmt_durable_command_identities").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM broker_orders").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (50, OrderStatus.ACKNOWLEDGED),
        (54, OrderStatus.CANCELLED),
        (56, OrderStatus.FILLED),
        (57, OrderStatus.REJECTED),
    ],
)
def test_callback_transitions_persist_in_oms(tmp_path, status_code, expected):
    cid = "cid-" + str(status_code)
    token = durable_submit(tmp_path, client_order_id=cid, command_id="cmd-" + str(status_code))
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    evidence = runtime.mapper(event(1, "order", order_payload(token, status_code)))
    assert evidence is not None
    runtime.ingest_broker_evidence(evidence)
    assert runtime.repository.get_status(FP, cid) is expected
    runtime.close()

    restarted = GuojinSimOmsRuntime(instance(tmp_path))
    assert restarted.repository.get_status(FP, cid) is expected
    restarted.close()


def test_callback_and_routed_snapshot_semantically_deduplicate(tmp_path):
    token = durable_submit(tmp_path, client_order_id="cid-dedup", command_id="cmd-dedup")
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    payload = order_payload(token, 50)
    first = runtime.mapper(event(1, "order", payload))
    assert first is not None
    assert runtime.ingest_broker_evidence(first).duplicate is False
    routed = dict(payload)
    routed.update(
        route_account_type="HUGANGTONG",
        route_account_fingerprint="sha256:" + "b" * 64,
    )
    batch = runtime.mapper.map_snapshot(
        event(
            2,
            "snapshot",
            {
                "account_fingerprint": FP,
                "account_type": "STOCK",
                "account": [],
                "positions": [],
                "orders": [routed],
                "deals": [],
                "query_errors": [],
            },
            source="active_query",
        )
    )
    assert batch.rejected_rows == 0
    second = runtime.ingest_broker_evidence(batch.evidence[0])
    assert second.duplicate is True
    assert runtime.repository.get_status(FP, "cid-dedup") is OrderStatus.ACKNOWLEDGED
    observations = runtime.evidence_journal.list_observations(FP, "cid-dedup")
    assert [row["classification"] for row in observations] == ["NEW", "SEMANTIC_DUPLICATE"]
    assert observations[1]["route_account_type"] == "HUGANGTONG"
    runtime.close()


def test_unregistered_and_transient_rows_remain_rejected(tmp_path):
    durable_submit(tmp_path, client_order_id="cid-known", command_id="cmd-known")
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    assert runtime.mapper(event(1, "order", order_payload("BQ" + "0" * 20, 50))) is None
    token = runtime.mapper.register_order(
        client_order_id="cid-transient", symbol="510300.SH", quantity=100
    )
    transient = order_payload(token, 50, broker_id="")
    assert runtime.mapper(event(2, "order", transient)) is None
    assert [item.reason for item in runtime.mapper.rejections[-2:]] == [
        "UNREGISTERED_TOKEN",
        "ORDER_ACCEPTED_NOT_SETTLED",
    ]
    runtime.close()
