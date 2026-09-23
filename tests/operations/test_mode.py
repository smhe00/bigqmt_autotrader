from datetime import datetime, timedelta, timezone

import pytest

from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import (
    ModeTransitionConflict,
    ModeTransitionDenied,
    RuntimeHealth,
    RuntimeModeController,
)
from bigqmt_autotrader.risk import RuntimeMode


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 11, 0, tzinfo=TZ)


def health(**changes):
    values = dict(
        database_healthy=True,
        oms_healthy=True,
        leader_held=True,
        reconciliation_complete=True,
        qmt_healthy=True,
        market_data_healthy=True,
        strategy_healthy=True,
    )
    values.update(changes)
    return RuntimeHealth(**values)


def controller(tmp_path, session="host-1"):
    conn = connect_database(tmp_path / "mode.sqlite3")
    initialize_database(conn)
    return conn, RuntimeModeController(conn, runtime_session_id=session, started_at=NOW)


def test_runtime_always_starts_disabled_and_audits_start(tmp_path):
    conn, ctl = controller(tmp_path)
    assert ctl.mode is RuntimeMode.DISABLED
    row = conn.execute(
        "SELECT from_mode, to_mode, actor FROM runtime_mode_transitions WHERE request_id=?",
        ("startup:host-1",),
    ).fetchone()
    assert tuple(row) == ("DISABLED", "DISABLED", "system")


def test_simulation_requires_health_and_explicit_nonlive_transition(tmp_path):
    _, ctl = controller(tmp_path)
    ctl.request_mode(
        request_id="observe", target=RuntimeMode.OBSERVE, actor="operator",
        reason="preflight", changed_at=NOW, health=health()
    )
    with pytest.raises(ModeTransitionDenied, match="health prerequisites"):
        ctl.request_mode(
            request_id="sim-bad", target=RuntimeMode.SIMULATION, actor="operator",
            reason="arm", changed_at=NOW, health=health(qmt_healthy=False)
        )
    assert ctl.mode is RuntimeMode.OBSERVE
    assert ctl.request_mode(
        request_id="sim-ok", target=RuntimeMode.SIMULATION, actor="operator",
        reason="arm", changed_at=NOW, health=health()
    )
    assert ctl.mode is RuntimeMode.SIMULATION


def test_live_modes_remain_forbidden(tmp_path):
    _, ctl = controller(tmp_path)
    for target in (RuntimeMode.LIVE_CANARY, RuntimeMode.LIVE_ARMED):
        with pytest.raises(ModeTransitionDenied, match="production Gate"):
            ctl.request_mode(
                request_id=f"live-{target.value}", target=target, actor="operator",
                reason="not authorized", changed_at=NOW, health=health()
            )
    assert ctl.mode is RuntimeMode.DISABLED


def test_health_loss_halts_mutation_mode_and_only_disabled_can_reset(tmp_path):
    _, ctl = controller(tmp_path)
    ctl.request_mode(
        request_id="observe", target=RuntimeMode.OBSERVE, actor="operator",
        reason="preflight", changed_at=NOW, health=health()
    )
    ctl.request_mode(
        request_id="sim", target=RuntimeMode.SIMULATION, actor="operator",
        reason="arm", changed_at=NOW, health=health()
    )
    assert ctl.enforce_health(
        request_id="health-halt", health=health(market_data_healthy=False),
        changed_at=NOW + timedelta(seconds=1)
    )
    assert ctl.mode is RuntimeMode.HALTED
    with pytest.raises(ModeTransitionDenied):
        ctl.request_mode(
            request_id="observe-again", target=RuntimeMode.OBSERVE, actor="operator",
            reason="unsafe reset", changed_at=NOW + timedelta(seconds=2), health=health()
        )
    ctl.request_mode(
        request_id="reset", target=RuntimeMode.DISABLED, actor="operator",
        reason="manual reset", changed_at=NOW + timedelta(seconds=3), health=health()
    )
    assert ctl.mode is RuntimeMode.DISABLED


def test_duplicate_request_is_idempotent(tmp_path):
    _, ctl = controller(tmp_path)
    kwargs = dict(
        request_id="observe", target=RuntimeMode.OBSERVE, actor="operator",
        reason="preflight", changed_at=NOW, health=health()
    )
    assert ctl.request_mode(**kwargs)
    assert not ctl.request_mode(**kwargs)
    assert ctl.mode is RuntimeMode.OBSERVE


def test_request_id_conflict_fails_closed(tmp_path):
    _, ctl = controller(tmp_path)
    ctl.request_mode(
        request_id="observe", target=RuntimeMode.OBSERVE, actor="operator",
        reason="preflight", changed_at=NOW, health=health()
    )
    with pytest.raises(ModeTransitionConflict):
        ctl.request_mode(
            request_id="observe", target=RuntimeMode.OBSERVE, actor="operator",
            reason="different", changed_at=NOW, health=health()
        )


def test_new_host_session_does_not_restore_prior_simulation_authority(tmp_path):
    path = tmp_path / "restart.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    first = RuntimeModeController(conn, runtime_session_id="host-1", started_at=NOW)
    first.request_mode(
        request_id="observe", target=RuntimeMode.OBSERVE, actor="operator",
        reason="preflight", changed_at=NOW, health=health()
    )
    first.request_mode(
        request_id="sim", target=RuntimeMode.SIMULATION, actor="operator",
        reason="arm", changed_at=NOW, health=health()
    )
    assert first.mode is RuntimeMode.SIMULATION
    conn.close()

    conn = connect_database(path)
    initialize_database(conn)
    second = RuntimeModeController(
        conn, runtime_session_id="host-2", started_at=NOW + timedelta(minutes=1)
    )
    assert second.mode is RuntimeMode.DISABLED

    with pytest.raises(ModeTransitionConflict):
        second.request_mode(
            request_id="sim", target=RuntimeMode.SIMULATION, actor="operator",
            reason="arm", changed_at=NOW, health=health()
        )
