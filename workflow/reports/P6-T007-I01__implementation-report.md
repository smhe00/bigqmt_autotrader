---
workflow_schema: 1
phase: P6
task_id: P6-T007
iteration: I01
task_key: P6-T007-I01
reply_to: workflow/tasks/P6-T007-I01__guojin-sim-resting-host-restart.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T007-I01__architect-review.md
---

# P6-T007-I01 Implementation Report

## Result
- Status: `REVIEW_READY`
- Runtime time: 2026-09-22 11:18:57–11:44:56 Asia/Shanghai (03:18:57–03:44:56 UTC)
- Implementation commit: eb080ae17c4c606594e522986744c52dbc17f5ca

## Pre-restart ACK
- Exact manifest: `guojin_sim`, `SIMULATION_CALIBRATION`, `simulation_only=true`, build `p5-simulation-calibration-7`, session `a699da30438c44c3bfe55c4d8a0ab214`, account fingerprint `sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702`.
- Fresh QMT snapshot sequence 2085 showed `510300.SH` sellable 300 and last price about 4.637. The one passive order was `SELL 100 510300.SH LIMIT 4.90`, client order ID `p6t007-resting-sell-510300-20260922`; deterministic Risk accepted with `RISK_OK`.
- Immutable submit command `simoms-f808511963e55ae5ec3a782cb61c564dbeb37f9eaf5488af`, token `BQ3335a3d9938b087ffcfa`, frame digest `sha256:1636b33b1d6d0d1366ff13dec32aab0244fbad9a2ceecadb519e6ec47c5e4f4e`. Its file reached `guojin_sim/commands/processed`; durable dispatch state `OBSERVED_PROCESSED`.
- QMT sequence 2105 `SIMULATION_SUBMIT_CALL_RETURNED` was control-plane only. The initial ORDER without broker ID (sequence 2106) was quarantined. Calibrated ORDER callback sequence 2107 had broker order ID `3504`, order ref `446149875865646904`, exact token, raw `50/51`, filled 0/100, remaining 100. It produced `BrokerEvidence ORDER_ACCEPTED`; OMS became `ACKNOWLEDGED` at 03:19:14.987875 UTC.

## Host restart
- Before stopping the first Host, the durable OMS row was `ACKNOWLEDGED`, broker order ID `3504`, filled 0, and the submit-dispatch count was one.
- The Host was stopped and restarted against the same `guojin_sim` manifest/session. Its log recorded `ready` and coherent `recovery_replay` from snapshot sequence 2085 through the current spool tail. The persisted durable identity row retained the same client order ID, token, session and processed submit command.
- After restart, active ORDER query observations retained broker order ID `3504`, token `BQ3335a3d9938b087ffcfa`, raw `50/51`, and zero fill. The first active-query accepted fact was admitted; subsequent equivalent facts were classified `SEMANTIC_DUPLICATE`.
- During cleanup, process inspection initially confused the diagnostic PowerShell process with a Host because its command text contained the Host arguments. A later read-only inspection confirmed no running Python Host and an expired leader lease. Process checks were narrowed to actual `python.exe` processes before restarting the single Host for final reconciliation. No duplicate writer was started.

## Zero replay
- Exactly one `SUBMIT_LIMIT` dispatch row and one processed submit command file exist for this client order; `submit_call_started=1`. There is one `SIMULATION_SUBMIT_CALL_RETURNED` result at QMT sequence 2105 and one broker order ID `3504` throughout.
- The restart and repeated callback/query evidence did not create another submit dispatch or broker submit. No blind retry was issued during transient `UNKNOWN -> RECONCILING` states.

## Cleanup cancel
- OMS issued one exact cancel for trusted broker order ID `3504` and persisted token `BQ3335a3d9938b087ffcfa`: command `simoms-8e13e869b13ab451271f4faad2cc911330551b7ddd04b858`, frame digest `sha256:9a22fa750b54a0eff7ad44784d20cbd4166650907689b1a561cd111856fc90d9`. Its file reached `guojin_sim/commands/processed`; durable dispatch state `OBSERVED_PROCESSED`.
- `SIMULATION_CANCEL_SIGNAL_SENT` at QMT sequence 2269 stayed control-plane. ORDER callback sequence 2270 carried the same identity, raw status `54/51`, filled 0. `BrokerEvidence ORDER_CANCELLED` advanced the OMS to `CANCELLED` at 03:44:56.197590 UTC; the later active-query fact was a semantic duplicate.
- Final durable row: `CANCELLED`, broker order ID `3504`, filled 0, `submit_call_started=1`, `cancel_call_started=1`. No unresolved `UNKNOWN` or `MANUAL_REVIEW` remains for this order.

## Mutation accounting
```text
guojin_sim submits = 1
guojin_sim cancels = 1
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
UNKNOWN blind retries = 0
```

## Verification
- Runtime evidence and durable-spool reconciliation: PASS for the same order across Host restart, one submit, one exact cancel and broker-evidence-backed terminal `CANCELLED`.
- Local repository suite: 453 tests passed in 11.10 s. FSM finite conformance PASS (196 pairs), bridge protocol PASS (4608 transitions), bridge schema PASS, Broker Evidence contract PASS (7200 cases), side-effect audit PASS and QMT deployment build check PASS.
- GitHub CI/TLC: pending the handoff push.

## Handoff
Prepared for standard Agent -> Architect handoff. The process-filter false positive and its correction are recorded above for review; no product-code modification was needed.
