# Project Status

Updated: 2026-09-16

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| Host Python baseline | **CPython 3.12** |
| QMT-side syntax target | **Built-in Python 3.6 compatible** |
| Observed Guojin QMT runtime | **CPython 3.6.8 / QMT 2.1.19.0; live-account and simulation instances PASS** |
| Observed Galaxy QMT terminal | **QMT 2.1.26.1; V05 discovered STOCK / HUGANGTONG / SHENGANGTONG; linked callback suppression PASS** |
| P0 / G0 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Risk engine | **PASS** |
| P3 Big QMT read-only | **PASS — multi-hour read/recovery/archive + V05 run_time deployment calibration complete** |
| P4 Big QMT execution bridge | **SHADOW DEPLOYMENT GATE PASS** |
| P5 Shadow / simulation / live canary | **BOUNDED GUOJIN_SIM MUTATION CALIBRATION PASS — OMS evidence mapper/live canary not enabled** |
| Production-account live trading allowed | **NO — galaxy/guojin remain source-level disabled** |
| QMT submit implemented | **GUOJIN_SIM ONLY — pinned simulation calibration artifact** |
| QMT cancel implemented | **GUOJIN_SIM ONLY — exact broker ID + broker-token match required** |
| P2 execution-authority policy | **SIMULATION only** |

## Broker-neutral account discovery

V05 now probes the standard QMT account-type namespace at runtime instead of
selecting a Galaxy- or Guojin-specific profile. Confirmed linked-account
ACCOUNT/POSITION observations are transported in `account_capabilities` and
retained by Host in a separate read-only view. Missing, `None`, mismatched and
exception results remain `UNCONFIRMED` or `DEGRADED`; they are never interpreted
as empty accounts. The selected OMS account identity and SHADOW command boundary
remain unchanged. Positively detected non-selected account callbacks are
suppressed from the single-account OMS stream; unknown types still fail closed.

Galaxy discovery: **PASS** for startup ACCOUNT/POSITION probing of `STOCK`,
`HUGANGTONG`, and `SHENGANGTONG`. The terminal also demonstrated that linked
ACCOUNT callbacks are delivered to the selected STOCK model instance; the
bridge now suppresses and counts those known linked callbacks without routing
them into the selected OMS stream. Galaxy redeployment and both Guojin
live-account and simulation-instance startup calibrations passed with healthy
read models, no query errors, no backlog, and zero quarantine.

## Multi-terminal spool isolation

Galaxy, Guojin live-account, and Guojin simulation instances do not share a
spool root. Three standalone V05 files embed their deployment instance and
atomically publish `instance.json` under
`D:\BigQMTData\spool\<instance_id>`. Host contains no broker registry: without
arguments it enumerates immediate child directories, validates each manifest
against the matching-session `bridge_ready`, and asks the operator to select.
`--instance-id` is an optional shortcut with identical validation. Each Host
process remains pinned to one terminal instance and account fingerprint. A
simulation mutation instance is hidden unless Host is started with
`--allow-simulation-mutation`, and its manifest must pin the current account
fingerprint and every calibration limit.

## P3 read plane

| Capability | State |
| --- | --- |
| Isolated spool roots | **PASS — `galaxy`, `guojin`, and `guojin_sim` independently discovered and healthy** |
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

Guojin simulation instance calibration (`guojin_sim`) additionally proved:

- independent manifest/session/spool identity under `D:\BigQMTData\spool\guojin_sim`;
- startup and 300-second periodic snapshots with 1 STOCK account, 2 positions,
  no query errors, and a healthy Host read model;
- `REQUEST_SNAPSHOT`, `SUBMIT_LIMIT`, and `CANCEL_ORDER` round trips with
  `live_side_effect=false`; submit/cancel returned only `SHADOW_ACCEPTED`;
- Host-only restart recovery from snapshot sequence 13 through command-result
  sequence 14 with zero backlog and zero quarantine.
- fingerprint-pinned mutation session `876fe6929be643e386d0e86b8b52f566`
  completed the two-submit calibration limit;
- resting order `10951` preserved broker token
  `BQ81ab7c6ddc8e40932700` and was cancelled with zero fill;
- fill order `10968` preserved broker token `BQ07a45d26d31b03b3a1ed` in both
  ORDER and DEAL, filling 100 `510300.SH` at `4.544` under trade `50037292`;
- active-query snapshot sequence 63 converged to 2 ORDER / 1 DEAL rows with no
  query errors and the same broker identities;
- the read-only calibration probe classified all 7 callback ORDER/DEAL rows as
  `MATCHED_KNOWN_TOKEN`; no OMS broker-evidence mapping was enabled.
- same-session robustness checks covered idempotent/conflicting publication,
  terminal-order cancel, token/order mismatch, stale session, wrong account,
  expiry, malformed transport, submit-limit exhaustion, and Host outage replay;
  final command state was 10 processed / 8 rejected / 0 unknown.

## P4 shadow execution plane

Bridge template: `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05.py`

Standalone deployments:

- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py`
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py`
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py`

Production-account build: `p4-shadow-command-spool-5`

Simulation calibration build: `p5-simulation-calibration-2`

Production-account safety state (`galaxy`, `guojin`):

- `TRADING_ENABLED=False`
- `execution_mode=SHADOW`
- `live_submit=False`
- `live_cancel=False`
- no `passorder`, order-lots, cancel/task mutation call surface
- QMT-side remains single-threaded and Python 3.6 compatible

Simulation-only safety state (`guojin_sim`):

- exact account fingerprint pinned in the generated standalone file;
- `execution_mode=SIMULATION_CALIBRATION`, never LIVE/LIVE_ARMED;
- only A-share BUY, exactly 100 shares, limit price, maximum 2,000 submit calls
  per QMT session (with the same finite ceiling for cancel calls);
- cancel requires one exact active-query match on both broker order ID and the
  deterministic `BQ...` broker token;
- commands must carry the current QMT session and explicit simulation marker;
- Host and publisher each require separate explicit simulation authorization;
- simulation dispatch results never enter the OMS SHADOW result journal and
  cannot create broker ACK state.
- simulation cancel publication is once-only per exact account/client/broker
  identity across inbox, claimed, processed, rejected, and unknown command
  states; query lag cannot trigger an automatic repeat cancel.

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

The safe `shadow_probe` CLI exposes all three command types. Its cancel path
publishes only to the durable SHADOW command spool and never invokes a broker
cancel API.

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

A read-only calibration projection recognizes broker tokens only when QMT `remark` exactly matches `BQ[0-9a-f]{20}`. It records raw `broker_order_id`, `order_ref`, `trade_id`, QMT status/submit-status codes and quantities. Guojin simulation has now proved exact token preservation across cancel and fill lifecycles. The projection deliberately performs **no QMT-status → OMS-status mapping yet**; raw simulation codes are not promoted into production-grade broker semantics.

QMT command results are durably journaled in OMS schema v5. Duplicate/conflicting command or QMT session/sequence identities fail closed. The `QmtBrokerTokenCalibration` observer matches only exact pre-registered tokens and never generates broker evidence; ORDER/DEAL remain quarantined until a separate OMS evidence-mapping gate passes.

## Verification

| Verification | State |
| --- | --- |
| Latest verified Python suite | **237 passed on Python 3.12** |
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
- P5 simulation mutation gate: `docs/P5_GUOJIN_SIMULATION_MUTATION_GATE.md`
- P5 simulation calibration result: `docs/P5_GATE_RESULT_20260916.md`

## Current checkpoint

**P0/P1/P2/P3 PASS. P4 SHADOW deployment gate PASS. P5 bounded Guojin
simulation submit/cancel/fill calibration PASS. OMS broker-evidence mapping,
LIVE_CANARY, and all production-account mutation remain disabled.**

The next checkpoint is a separately reviewed OMS evidence-mapping contract
based on replay-safe ORDER/DEAL/query convergence. No mutation authority exists
in the Galaxy or Guojin production-account artifacts.
