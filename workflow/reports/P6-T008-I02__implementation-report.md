---
workflow_schema: 1
phase: P6
task_id: P6-T008
iteration: I02
task_key: P6-T008-I02
reply_to: workflow/tasks/P6-T008-I02__runtime-tick-freshness-refresh.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T008-I02__architect-review.md
---

# P6-T008-I02 Implementation Report

## Result
- Status: REVIEW_READY
- Initial implementation: b3abc709521df180d4656e0decfb62d3547479d6
- Final implementation: 80fcdeae600b9583c0704ce98db69d4f079ea928
- CI run: 35697259833 — SUCCESS

## Runtime refresh design

- Existing REQUEST_SNAPSHOT is reused; no new command type was added.
- V05 common template now invokes an optional read-only `_runtime_snapshot_tick_refresh` hook during REQUEST_SNAPSHOT.
- The hook is behaviorally active only when the simulation diagnostics exist (`_SIMULATION_INSTRUMENT_CANDIDATES`, tick-state/record/publish functions). Galaxy and production Guojin have no simulation candidate set, so the hook returns without market-data polling or authority change.
- On guojin_sim the hook calls QMT get_full_tick for every bounded current simulation candidate even when that symbol was previously observed.
- Each result flows through existing exact-symbol normalization; broker tick_time is preserved while local last_callback_ms is refreshed.
- A new instrument_tick_capabilities event is published after each requested refresh.
- Missing get_full_tick, exceptions, or symbol mismatch remain read-only/fail-closed.
- Simulation deployment build is now p5-simulation-calibration-8.

## Regression coverage

- previously observed 00700.HGT is re-polled and old price 430.4 is replaced by newer 450.4;
- local observation timestamp advances;
- exact-symbol mismatch remains invalid evidence;
- unavailable get_full_tick produces read-only unavailable evidence with zero submit/cancel calls;
- REQUEST_SNAPSHOT invokes the tick refresh hook before final flush/result;
- deployment generator and generated artifacts are consistent.

## Safety

broker mutation during implementation/test = 0
production authority expansion = 0
simulation submit/cancel code paths unchanged
production Guojin LIVE_CANARY build/authority unchanged

## Verification

- pytest: 457 passed
- workflow contract: PASS
- side-effect audit: PASS
- deployment generator consistency: PASS
- bridge protocol/schema/BrokerEvidence finite verification: PASS
- permanent TLC suite: PASS
- GitHub jobs test/formal-verification: SUCCESS

## Handoff

Ready for Architect review. After PASS, deploy/reload p5-simulation-calibration-8 locally and rerun the HGT linked-route fill in the next small iteration.
