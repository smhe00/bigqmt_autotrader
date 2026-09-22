---
workflow_schema: 1
phase: P6
task_id: P6-T008
iteration: I01
task_key: P6-T008-I01
reply_to: workflow/tasks/P6-T008-I01__guojin-sim-oms-hgt-linked-fill.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T008-I01__architect-review.md
---

# P6-T008-I01 Implementation Report

## Result
- Status: `REVIEW_READY`
- Runtime time: 2026-09-22 14:22–14:28 Asia/Shanghai.
- Outcome: `BLOCKED_AT_PREFLIGHT`; no OMS order was submitted. The current bridge cannot refresh or publish exact-route tick evidence on Host request after its startup probe window. This is a distinct prerequisite defect, not a linked-route fill result.

## Preflight
- Pinned manifest: `guojin_sim`, `SIMULATION_CALIBRATION`, `simulation_only=true`, build `p5-simulation-calibration-7`, session `a699da30438c44c3bfe55c4d8a0ab214`, STOCK OMS fingerprint `sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702`.
- Active `account_capabilities` sequence 3494 at 2026-09-22 14:26:29 showed `HUGANGTONG` DETECTED with route fingerprint `sha256:e475f1a12b1bede72aafada79c0d876e3549a33985b6ce0d3df6baca9fa6c43d` and `00700.HGT` 100 sellable, route-position `last_price=450.4`. This is linked-route/account evidence, not a timestamped exact-route tick and not a replacement for the pinned STOCK OMS identity.
- Exact `00700.HGT` instrument detail exists in sequence 30 (`exchange_id=HK`, `hsgt_flag=5`), but was emitted 2026-09-21 14:52:40. Latest exact-symbol `00700.HGT` tick evidence is sequence 31 at the same time, with tick time 2026-09-21 14:52:31 and `last_price=430.4`. No current-day `instrument_tick_capabilities` event was present in the current-session inbox or processed spool at 14:28 on 2026-09-22.
- Prior read-only preflight found no unresolved `UNKNOWN` or `MANUAL_REVIEW` and a single active Host leader. No production/Galaxy/generic command root was used.

## HGT OMS submit
- Not attempted. The task requires fresh exact-route tick before mutation; yesterday's quote and today's route-position `last_price` do not satisfy that check. No client order ID, Risk decision or submit command exists for this iteration.

## Linked-route BrokerEvidence
- Not applicable: zero submit, so no ORDER/DEAL or `FILLED` claim.

## Identity / idempotency
- No order/token was allocated. The manifest and read-only request retained the pinned STOCK fingerprint. No duplicate submit or blind retry occurred.

## Mutation accounting
```text
guojin_sim submits = 0
guojin_sim cancels = 0
guojin_sim read-only REQUEST_SNAPSHOT = 1
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
UNKNOWN blind retries = 0
```

## Verification
- Host read-only `REQUEST_SNAPSHOT` command `3ac801e98b9548bb877c2dc77c569b13` was durably processed. QMT emitted `account_capabilities` sequence 3494, `snapshot` sequence 3495 and `command_result` sequence 3496 with `SNAPSHOT_EMITTED`, `live_side_effect=false`. It emitted no `instrument_tick_capabilities` event for this command.
- Code inspection agrees: `REQUEST_SNAPSHOT` calls only `read_account_capabilities`, `read_snapshot` and `flush_transport`; tick publication occurs during startup probe/first quote callback. The one-second `instrument_probe_tick` stops after its bounded startup attempts. There is no current Host command for a fresh exact-route tick.
- No product-code change or trade-mutation test was made. Workflow contract verification is to be run with the handoff; full CI/formal cannot turn this runtime preflight into a fill PASS.

## Deviations / blockers
- This is a bridge/Host protocol gap. A separate, bounded iteration should add a read-only, session-bound Host-requested exact-symbol tick refresh (or equivalent periodic fresh publication), with source/tick timestamps, exact-symbol validation, timeout/stale failure-closed handling and regression coverage. After one deployment of that capability, normal trading should **not** require daily V05 restarts. `P6-T008-I01` must be rerun in a valid HGT window after fresh evidence is available; do not waive its preflight or treat a position price as tick evidence.

## Handoff
Hand back to Architect as an explicitly blocked runtime gate so the distinct refresh prerequisite can be scoped separately. `REVIEW_READY` is a review handoff status, not a claim that the linked-route fill gate passed.
