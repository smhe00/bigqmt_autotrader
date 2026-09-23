---
workflow_schema: 1
phase: P6
task_id: P6-T010
iteration: I01
task_key: P6-T010-I01
reply_to: workflow/tasks/P6-T010-I01__qmt-session-rollover-runtime.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T010-I01__architect-review.md
---

# P6-T010-I01 Implementation Report

## Result
- Status: `REVIEW_READY`
- Runtime time: `2026-09-23 10:37-10:47 Asia/Shanghai`
- Outcome: `PASS`. One broker-ACKed passive simulation order survived an
  intentional QMT V5 session rollover without submit replay, was recovered by
  exact active-query identity, and was cancelled exactly once.

## Evidence
- Authority and boundary: GitHub `main`
  `a44413afd204d0935eb32498b8b23afc6ee00f58` authorized only
  `P6-T010-I01`. The target remained `guojin_sim`, build
  `p5-simulation-calibration-8`, `SIMULATION_CALIBRATION`,
  `simulation_only=true`, pinned STOCK fingerprint
  `sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702`.
- Preflight snapshot sequence 987 was healthy and showed `510300.SH`
  `quantity=300`, `sellable_quantity=300`, reference price `4.603`, with no
  unresolved `UNKNOWN` or `MANUAL_REVIEW`.
- Normal OMS API submitted exactly one passive `SELL 100 510300.SH LIMIT 4.900`
  using client ID `p6t010-rollover-sell-510300-20260923`. Risk returned
  `RISK_OK`. The immutable submit was command
  `simoms-61032c8bf3415909c4eee286f9fe66aa803e052b0aead8ba`, digest
  `sha256:602801ed703a51394f3eff1c8d462e71b22d4610aab45c7e15834c5bfe564a53`,
  token `BQc3b916b82feb910e213a`, old QMT session
  `2473e2b97ee344fca3bdddee80fd3f85`.
- `SIMULATION_SUBMIT_CALL_RETURNED` at old-session sequence 1018 remained
  control-plane only. ORDER callback sequence 1020 supplied broker order ID
  `2520`, order ref `446149875865646909`, raw `50/51`, zero fill and remaining
  100. Calibrated `ORDER_ACCEPTED` BrokerEvidence alone moved OMS to
  `ACKNOWLEDGED`.
- The user intentionally restarted only the V5 model. Manifest session changed
  to `3578dff2dd104b15a04836a07a06e994`. The old Host emitted
  `session_rollover_restart_required` with both pinned and incoming session IDs,
  retained the event and exited; it did not silently continue.
- Required Host recovery against the new manifest began with `last_sequence=0`.
  New-session active-query snapshots 3 and 25 recovered the same resting order:
  client identity from token, broker order ID `2520`, order ref
  `446149875865646909`, price `4.9`, raw `50/51`, zero fill. These facts were
  semantic duplicates of the original ACK and did not create another submit.
- Across rollover, the database retained exactly one SUBMIT dispatch, pinned to
  the old session and `OBSERVED_PROCESSED`; `submit_call_started=1`. No new
  SUBMIT command or broker order ID appeared.
- Normal OMS cancellation published exactly one new-session command
  `simoms-39f98ea813eaa8ce7e09598391fa4816e7886240bae0c6d4`, digest
  `sha256:40bdbbc10a478d572b284c440767231c3695b5fa438b3df5fa3b615b1a94389e`,
  with the same token and exact broker order ID `2520`.
- `SIMULATION_CANCEL_SIGNAL_SENT` at sequence 60 remained control-plane only.
  ORDER callback sequence 61 carried raw `54/51` and emitted calibrated
  `ORDER_CANCELLED`, advancing OMS to `CANCELLED`. Final active-query snapshot
  sequence 76 independently confirmed status 54, cancelled quantity 100,
  frozen quantity 0 and sellable quantity restored to 300; its evidence was a
  semantic duplicate.
- Final persistent row: `CANCELLED`, broker order ID `2520`, filled 0,
  `submit_call_started=1`, `cancel_call_started=1`. No `UNKNOWN` or
  `MANUAL_REVIEW` remains. The final Host was stopped after evidence capture.

## Mutation accounting
- `guojin_sim` submit: `1 / <=1`
- `guojin_sim` cancel: `1 / <=1`
- duplicate submit/cancel: `0 / 0`
- production `guojin`, `galaxy`, generic mutation: `0`
- Read-only snapshot commands before and after the scenario had
  `live_side_effect=false` and are not mutation calls.

## Verification
- Runtime invariant: PASS for session change detection, fail-closed old Host,
  zero replay, exact identity recovery and terminal cancellation.
- Python suite: `459 passed, 1 cache warning in 89.54s`.
- FSM conformance: PASS (`196` state/request pairs).
- Bridge ingress/spool conformance: PASS (`4608` transitions plus command
  idempotency/conflict/expiry).
- Bridge schema drift: PASS.
- Broker Evidence Contract: PASS (`7200` cases).
- Side-effect surface audit: PASS.
- Standalone QMT deployment consistency check: PASS.
- The first CI invocation from repository root lacked `src` on the module path;
  it performed no runtime mutation. The corrected run set the repository `src`
  path explicitly and produced the results above. Temporary test artifacts were
  removed afterward.
- Product code changed: none.

## Handoff
Ready for the standard Agent -> Architect review. No later prebuilt runtime task
was executed or activated.
