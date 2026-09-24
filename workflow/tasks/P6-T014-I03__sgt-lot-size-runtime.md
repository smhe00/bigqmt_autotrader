---
workflow_schema: 1
phase: P6
task_id: P6-T014
iteration: I03
task_key: P6-T014-I03
state: CHANGES_REQUIRED
owner: agent
audit_base_commit: 904d90e758cadcad1ad4bf61a1166496ec179c8c
expected_report: workflow/reports/P6-T014-I03__implementation-report.md
expected_review: workflow/reviews/P6-T014-I03__architect-review.md
---

# SGT board-lot preflight and exact-fill runtime

## Objective

Complete the remaining SGT exact-fill runtime gate with one 100-share-compatible
candidate.  Preflight the lot-size evidence before mutation; use `00700.SGT`
only if fresh exact tick, SHENGANGTONG route, cash and prior 100-share broker
evidence remain coherent.

## Scope

Runtime/report only; no product-code changes.  Target remains exclusively
`guojin_sim`, current pinned session, `SIMULATION_CALIBRATION`,
`simulation_only=true`, build `p5-simulation-calibration-8`, STOCK OMS identity.
Use `GuojinSimOmsRuntime.execute_intent()` and one marketable LIMIT BUY 100.

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T014-I03__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T014-I03__architect-review.md

## Safety boundaries

- `guojin_sim` submit <= 1; cleanup cancel <= 1 only if ACKNOWLEDGED and open.
- Production Guojin/Galaxy/generic mutation = 0.
- No blind retry, no quantity above 100 and no use of `01810.SGT`.
- Stop on stale tick, route/session/account ambiguity, UNKNOWN or insufficient
  board-lot evidence.

## Required verification

Capture fresh exact `00700.SGT` tick, SHENGANGTONG route fingerprint, available
cash, prior accepted 100-share linked-route evidence and current unresolved
UNKNOWN/MANUAL_REVIEW count.  Record the full command, token, digest, broker
IDs, lifecycle, fill quantity and duplicate behavior.  Run the workflow,
dependency and side-effect gates; reuse the already-green full CI commit unless
code changes.

## Exit criteria

Exactly one Core submit crosses the simulator boundary and BrokerEvidence
converges exactly once to FILLED 100 without unresolved ambiguity, duplicate
fill or production mutation.  Otherwise stop at the first deterministic gate
and record zero blind retries.
