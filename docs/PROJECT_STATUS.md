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
| P3 Big QMT read-only | **PASS — multi-hour read/recovery/archive + V05 run_time deployment calibration complete** |
| P4 Big QMT execution bridge | **SHADOW CODE GATE PASS — durable command-result/OMS reconciliation added; no live broker mutation** |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| P2 execution-authority policy | **SIMULATION only** |

## P3 read plane

| Capability | State |
| --- | --- |
| Fixed spool root | **PASS — `D:\BigQMTData\spool`** |
| ACCOUNT/POSITION/ORDER/DEAL active query | **PASS at query/schema level — calibrated snapshot: 1 / 8 / 1 / 2 rows, `query_errors=[]`** |
| Callback subscription | **PASS — `ContextInfo.set_account(account)`** |
| ACCOUNT callback | **PASS** |
| POSITION callback | **PASS** |
| 300 s independent active reconcile | **PASS — real QMT observations exactly 5 minutes apart** |
| QMT event transport | **PASS — atomic file publication; observed `dropped_events=0`, `transport_failures=0`** |
| Host ingestion/read model | **PASS — account/session/sequence validation; gap/session change fail-close** |
| Host-only restart recovery | **PASS — coherent current session/account replay from clean snapshot** |
| Filesystem/semantic quarantine | **PASS — zero in clean long-run and V05 calibration** |
| Archive integrity | **PASS — clean snapshot convergence + manifest/checkpoint + SHA-256 + post-commit exact cleanup** |
| Auto archive policy | **HARDENED — only past UTC+08 calendar days** |
| Host status logging | **HARDENED — change-driven + 300 s healthy heartbeat; session-aware diagnostics** |

Multi-hour real-QMT evidence:

- QMT remained healthy with 66 emitted ACCOUNT heartbeats and 3869 suppressed duplicate callbacks;
- no QMT event drops or transport failures were observed;
- Host remained `read_model_healthy=true`, `spool_pending=0`, with zero filesystem or semantic quarantine;
- Host event accounting reconciled exactly;
- Host restart replay recovered the clean current stream;
- the closed-day archive committed 28 events with no reasons and an integrity SHA-256 checkpoint.

V05 deployment calibration additionally proved:

- `command_timer_registered=true` with `1nSecond` command cadence;
- `snapshot_timer_registered=true` with `300nSecond` reconciliation cadence;
- `REQUEST_SNAPSHOT` Host→QMT→Host round-trip completed with `SNAPSHOT_EMITTED`, `live_side_effect=false`;
- the read model remained healthy with zero quarantine/backlog.

## P4 shadow execution plane

Bridge: `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05.py`

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

An orphaned claimed command becomes `UNKNOWN_ORPHANED`; it is never blindly replayed.

Implemented command types:

- `SUBMIT_LIMIT` — SHADOW only
- `CANCEL_ORDER` — SHADOW only
- `REQUEST_SNAPSHOT` — real read-only snapshot request

Order identity:

- durable `client_order_id`
- deterministic 22-character `BQ...` broker token derived from `(account_fingerprint, client_order_id)`
- token fits calibrated QMT `userOrderId` / `m_strRemark` `<24` constraint
- raw broker account ID is not present in Host command frames

Real-QMT SHADOW submit calibration proved:

- `client_order_id=shadow-test-001`
- `broker_token=BQ705de59e1227a73471cb`
- QMT returned `SHADOW_ACCEPTED` within the 1-second command cadence
- `live_side_effect=false`
- Host ingested the `command_result` while remaining healthy
- no ORDER/DEAL callback was produced, as expected because no broker mutation exists

### OMS command-result semantics

`command_result` now has a dedicated OMS control-plane sink. It is explicitly **not broker evidence**:

- `SHADOW_ACCEPTED` never creates `ACKNOWLEDGED`;
- if a result races a durable `SUBMITTING` or `CANCEL_PENDING` reservation, it can only converge that ambiguous boundary to `UNKNOWN`;
- if the OMS is already `UNKNOWN`, `SHADOW_ACCEPTED` may only begin `RECONCILING`;
- actual `ACKNOWLEDGED / PARTIALLY_FILLED / FILLED / CANCELLED / REJECTED` transitions remain reserved for calibrated broker ORDER/DEAL/query evidence.

Host diagnostics now expose `session_id`; `command_result` logs include command/client/token/result/mode/live-side-effect fields, while bridge errors expose their code. This removes ambiguity after QMT restarts.

### ORDER/DEAL calibration boundary

A read-only calibration projection now recognizes broker tokens only when QMT `remark` exactly matches `BQ[0-9a-f]{20}`. It records raw `broker_order_id`, `order_ref`, `trade_id`, QMT status/submit-status codes and quantities. It deliberately performs **no QMT-status → OMS-status mapping yet**. That mapping requires observed Guojin ORDER/DEAL broker evidence before it can be trusted.

QMT command results are durably journaled in OMS schema v5. Duplicate/conflicting command or QMT session/sequence identities fail closed. The `QmtBrokerTokenCalibration` observer matches only exact pre-registered tokens and never generates broker evidence; ORDER/DEAL remain quarantined until the separate calibration gate passes.

## Verification

| Verification | State |
| --- | --- |
| Latest verified Python suite | **197 passed on Python 3.12** |
| QMT-side Python 3.6 syntax contract | **PASS** |
| Broker mutation-call static audit | **PASS** |
| FSM implementation/formal conformance | **PASS** |
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
- P4 shadow gate: `docs/P4_GATE_RESULT_20260915.md`
- P4 ORDER/DEAL token calibration: `docs/P4_ORDER_DEAL_BROKER_TOKEN_CALIBRATION.md`

## Current checkpoint

**P0/P1/P2/P3 PASS. P4 SHADOW code gate PASS; ORDER/DEAL broker lifecycle calibration remains pending. Live trading remains disabled and unimplemented.**

The next checkpoint is observation-only ORDER/DEAL + `m_strRemark` calibration using the documented quarantine path. No broker mutation gate may be opened from the current status.
