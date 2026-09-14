# Project Status

Updated: 2026-09-15

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| Host Python baseline | **CPython 3.12** |
| QMT-side syntax target | **Built-in Python 3.6 compatible** |
| Observed Guojin QMT runtime | **CPython 3.6.8 / QMT 2.1.19.0** |
| P0 / G0 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Risk engine | **PASS** |
| P3 Big QMT read-only | **CODE GATE PASS — multi-hour V04 real-QMT read/recovery/archive calibration PASS; V05 run_time deployment calibration pending** |
| P4 Big QMT execution bridge | **IN PROGRESS — durable SHADOW command round-trip implemented; no live broker mutation** |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| P2 execution-authority policy | **SIMULATION only** |

## P3 read plane

| Capability | State |
| --- | --- |
| Fixed spool root | **PASS — `D:\BigQMTData\spool`** |
| ACCOUNT/POSITION/ORDER/DEAL active query | **PASS at query/schema level — latest calibrated snapshot: 1 / 8 / 1 / 2 rows, `query_errors=[]`** |
| Callback subscription | **PASS — `ContextInfo.set_account(account)`** |
| ACCOUNT callback | **PASS** |
| POSITION callback | **PASS — 8-position initial callback replay observed and semantically calibrated** |
| ORDER/DEAL callback status semantics | **PENDING P4 calibration** |
| QMT edge ACCOUNT dedup | **PASS — change immediate; unchanged heartbeat 300 s** |
| QMT event transport | **PASS — atomic file publication; observed `dropped_events=0`, `transport_failures=0`** |
| Host ingestion/read model | **PASS — account/session/sequence validation; gap/session change fail-close** |
| Host-only restart recovery | **PASS — coherent current session/account replay from clean snapshot** |
| Filesystem/semantic quarantine | **PASS — zero in clean long-run calibration** |
| Archive integrity | **PASS — clean snapshot convergence + manifest/checkpoint + SHA-256 + post-commit exact cleanup** |
| Auto archive policy | **HARDENED — only past UTC+08 calendar days; never finalizes a still-live same-day producer** |
| Host status logging | **HARDENED — change-driven + unchanged heartbeat every 300 s by default** |

Multi-hour real-QMT evidence (23:17–04:51 calibration):

- QMT remained healthy with 66 emitted ACCOUNT heartbeats and 3869 suppressed duplicate callbacks;
- no QMT event drops or transport failures were observed;
- Host remained `read_model_healthy=true`, `spool_pending=0`, with zero filesystem or semantic quarantine;
- Host event accounting reconciled with QMT: 2 snapshots + 8 position callbacks + 66 account callbacks = 76;
- Host restart replay recovered the clean current stream;
- the closed-day archive committed 28 source events with no reasons and an integrity SHA-256 checkpoint.

P3 code closeout replaces `handlebar`-driven pseudo-periodic snapshot timing with an independent QMT `run_time` full-snapshot timer in V05. The new timer still requires one real Guojin deployment observation before the deployment checkpoint is marked complete.

## P4 shadow execution plane

New bridge: `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05.py`

Build: `p4-shadow-command-spool-1`

Safety state:

- `TRADING_ENABLED=False`
- `execution_mode=SHADOW`
- `live_submit=False`
- `live_cancel=False`
- no `passorder`, order-lots, cancel/task mutation call surface
- QMT-side remains single-threaded and Python 3.6 compatible

Timing:

- Host event spool poll: 0.2 s default
- QMT command timer: **1 second** via `run_time`
- QMT full active-query reconcile: **300 seconds** via independent `run_time`
- broker callbacks: event-driven and immediately flushed

Durable command states:

```text
commands/inbox
    -> atomic QMT claim
commands/claimed
    -> processed | rejected | unknown
```

A command found orphaned in `claimed` after restart is moved to `unknown` and emits `UNKNOWN_ORPHANED`; it is never blindly replayed.

Implemented command types:

- `SUBMIT_LIMIT` — SHADOW only
- `CANCEL_ORDER` — SHADOW only
- `REQUEST_SNAPSHOT` — real read-only snapshot request

Order identity:

- durable `client_order_id`
- deterministic 22-character `BQ...` broker token derived from `(account_fingerprint, client_order_id)`
- token fits calibrated QMT `userOrderId` / `m_strRemark` `<24` constraint
- raw broker account ID is not present in Host command frames

Host accepts `command_result` events but does not treat `SHADOW_ACCEPTED` as broker evidence. `QmtShadowDriver` publishes the durable command then intentionally returns outcome-unknown semantics to the OMS, preserving the no-blind-resend model until actual broker callback/query evidence exists.

Safe probe CLI:

```text
python -m bigqmt_autotrader.qmt.shadow_probe ... snapshot
python -m bigqmt_autotrader.qmt.shadow_probe ... submit ...
```

Both operate against the command spool; V05 has no live trading call.

## Verification

| Verification | State |
| --- | --- |
| Latest verified Python suite | **184 passed on Python 3.12** |
| QMT-side Python 3.6 syntax contract | **PASS** |
| Broker mutation-call static audit | **PASS** |
| FSM implementation/formal conformance | **196 / 196** state-request pairs PASS |
| TLC OrderFSM | **PASS** |
| TLC SubmitProtocol | **PASS** |
| TLC LeaderLease | **PASS** |
| TLC EvidenceReplay | **PASS** |
| TLC PreSubmitRecovery | **PASS** |
| TLC RiskPrecedence | **PASS** |

## Gate documents

- P1: `docs/P1_GATE_RESULT_20260912.md`
- P2: `docs/P2_GATE_RESULT_20260913.md`
- P3: `docs/P3_GATE_RESULT_20260915.md`
- P3 Guojin calibration: `docs/P3_GUOJIN_QMT_CALIBRATION_20260914.md`
- P3 archive contract: `docs/P3_DAILY_SPOOL_ARCHIVE.md`
- P4 shadow boundary: `docs/P4_SHADOW_BRIDGE_SCOPE.md`

## Current checkpoint

**P0/P1/P2 PASS. P3 code gate PASS, V05 deployment calibration pending. P4 SHADOW bridge IN PROGRESS. Live trading remains disabled and unimplemented.**

The next required real-QMT test is intentionally side-effect-free: deploy V05 in Model Trading, confirm both `run_time` timers register, issue `REQUEST_SNAPSHOT` through the shadow probe, verify consumption within the 1-second command cadence, and verify `snapshot + command_result` arrive at Host with `read_model_healthy=true`. Only after that round-trip passes should the project design a separate P4 broker-mutation gate.
