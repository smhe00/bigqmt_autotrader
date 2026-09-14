# P3 Big QMT Read-Only Gate Result — 2026-09-15

## Decision

**P3 GATE: PASS**

The Guojin V05 deployment calibration is now complete. The real QMT runtime has verified the independent `run_time` timers, read-only active reconciliation, the durable Host→QMT command path, and QMT→Host `command_result` return path while live broker mutation remains disabled.

## Environment

- Guojin QMT 2.1.19.0
- built-in CPython 3.6.8
- fixed spool root `D:\BigQMTData\spool`
- QMT V05 build `p4-shadow-command-spool-1`
- Host Python 3.12
- `execution_mode=SHADOW`
- `trading_enabled=false`
- `live_submit=false`
- `live_cancel=false`

## Long-run read-plane evidence

Earlier V04/V05-compatible read-plane calibration established:

- initial active snapshot: 1 ACCOUNT, 8 POSITION, 1 ORDER, 2 DEAL, `query_errors=[]`
- ACCOUNT raw callbacks continued overnight and edge dedup remained stable
- at the end of the multi-hour run: `account_callbacks_emitted=66`, `account_callbacks_suppressed=3869`
- QMT `dropped_events=0`
- QMT `transport_failures=0`
- Host remained `read_model_healthy=true`
- Host `spool_pending=0`
- filesystem quarantine and semantic quarantine remained zero
- Host business-event count reconciled exactly: 2 snapshots + 8 position callbacks + 66 account callbacks = 76
- Host-only restart recovery found the clean snapshot, replayed the coherent current stream and returned healthy
- daily archive committed 28 events with no reasons and SHA-256 integrity checkpoint

## V05 real-QMT deployment evidence

At 06:24:49 the Guojin model reported:

- `bridge_build=p4-shadow-command-spool-1`
- `command_timer_registered=true`
- `snapshot_timer_registered=true`
- `command_tick_period=1nSecond`
- `snapshot_timer_period=300nSecond`
- `callback_subscription=true`
- `query_errors=[]`
- `dropped_events=0`
- `transport_failures=0`
- `live_submit=false`
- `live_cancel=false`

The periodic active-query timer then emitted snapshots exactly five minutes apart (for example 06:29:49 and 06:34:49), proving the 300-second reconciliation timer is independent of daily-bar `handlebar` activity.

### Read-only command round-trip

A Host-side `REQUEST_SNAPSHOT` probe was durably published with command id:

`b9c49e1b324e4445bb7b0f520fbb7835`

QMT consumed it on the 1-second command timer, emitted a fresh snapshot, then returned:

- `command_type=REQUEST_SNAPSHOT`
- `result_status=SNAPSHOT_EMITTED`
- `execution_mode=SHADOW`
- `live_side_effect=false`

Host ingested the resulting snapshot and `command_result` with `needs_resync=false`, `read_model_healthy=true`, zero quarantine and zero pending spool backlog.

### SHADOW submit transport round-trip

A `SUBMIT_LIMIT` SHADOW probe used:

- `client_order_id=shadow-test-001`
- `broker_token=BQ705de59e1227a73471cb`
- `command_id=c6b9fde28ac04f8a998b28fae39d1ec1`

QMT returned `SHADOW_ACCEPTED` in the same second with `live_side_effect=false`. Host ingested the command result while remaining healthy. No ORDER or DEAL callback was produced, which is the correct result because V05 contains no broker mutation call.

## P3 closeout changes

### Archive finalization

Automatic archive handles only calendar days strictly earlier than the current UTC+08 date. Same-day finalization is forbidden while QMT may still publish valid heartbeats or reconciliation snapshots.

### Host status logging

Status summary is change-driven, with an unchanged healthy heartbeat at most every 300 seconds by default.

### Active reconciliation scheduling

V05 uses an independent `run_time` task for a full read-only snapshot every 300 seconds. `handlebar` is not used as a timer.

## Safety result

P3/P4-shadow code continues to satisfy:

- no live `passorder`
- no live order-lots API
- no live cancel/task mutation call
- no socket/threading/multiprocessing dependency on the QMT side
- Python 3.6 syntax contract for QMT-side bridge
- account/session/sequence fail-close validation
- durable atomic event publication
- coherent-session Host restart replay

## Gate boundary

P3 is closed as **PASS**. It establishes the authoritative broker read plane, periodic reconciliation, and durable recovery substrate. It does **not** authorize or implement live trading.

P4 may continue with OMS command-result reconciliation and ORDER/DEAL correlation calibration. Any future broker mutation requires a separate explicit gate and separate authorization.
