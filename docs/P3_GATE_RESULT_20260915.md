# P3 Big QMT Read-Only Gate Result — 2026-09-15

## Decision

**CODE GATE: PASS**

**Guojin V05 deployment calibration: PENDING** — the V04 read-only path has already passed multi-hour real-QMT calibration; V05 changes only timer scheduling and adds a disabled-live-trading shadow command plane. The V05 `run_time` registrations must be observed once in Guojin QMT before the deployment checkpoint is closed.

## Real-QMT evidence already observed

Environment:

- Guojin QMT 2.1.19.0
- built-in CPython 3.6.8
- fixed spool root `D:\BigQMTData\spool`
- QMT build `p3-file-spool-2`
- Host Python 3.12
- trading disabled

Long-run observation from approximately 23:17 to 04:51:

- initial active snapshot: 1 ACCOUNT, 8 POSITION, 1 ORDER, 2 DEAL, `query_errors=[]`
- ACCOUNT raw callbacks continued overnight and edge dedup remained stable
- at 04:51: `account_callbacks_emitted=66`, `account_callbacks_suppressed=3869`
- QMT `dropped_events=0`
- latest observed full snapshot: `transport_failures=0`, `transport_persisted=72`
- Host remained `read_model_healthy=true`
- Host `spool_pending=0`
- filesystem quarantine and semantic quarantine remained zero
- Host business-event count reconciled exactly: 2 snapshots + 8 position callbacks + 66 account callbacks = 76
- Host-only restart recovery found the clean snapshot, replayed the coherent current stream and returned healthy
- daily archive committed 28 events with no reasons and SHA-256 integrity checkpoint

## P3 closeout changes

### Archive finalization

Automatic archive now handles only calendar days strictly earlier than the current UTC+08 date. Same-day 16:10 finalization was removed because QMT can continue publishing valid account heartbeats and reconciliation snapshots after market close. This avoids late-event races against an immutable archive.

### Host status logging

Status summary is now change-driven:

- any summary-state change emits immediately
- an unchanged healthy state emits a heartbeat at most every 300 seconds by default

This removes repeated one-minute log noise without reducing anomaly visibility.

### Active reconciliation scheduling

The replacement QMT bridge V05 no longer treats `handlebar` as a timer. It registers an independent `run_time` task for a full read-only snapshot every 300 seconds. `handlebar` is retained only for non-blocking transport flush compatibility.

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

P3 establishes the authoritative broker read plane and durable recovery/reconciliation substrate. It does **not** authorize or implement live trading.

The next runtime checkpoint is V05 real-QMT calibration:

1. both `run_time` registrations succeed;
2. 300-second periodic snapshots are observed independently of daily-bar `handlebar` activity;
3. the 1-second command timer consumes a read-only `REQUEST_SNAPSHOT` shadow command;
4. QMT emits `command_result` and Host ingests it while remaining healthy.
