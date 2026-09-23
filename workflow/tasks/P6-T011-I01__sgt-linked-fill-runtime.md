---
workflow_schema: 1
phase: P6
task_id: P6-T011
iteration: I01
task_key: P6-T011-I01
state: PLANNED
owner: architect
audit_base_commit: d3fb18ed45f4ff2ac0b68db396301999288bb0b1
expected_report: workflow/reports/P6-T011-I01__implementation-report.md
expected_review: workflow/reviews/P6-T011-I01__architect-review.md
---

# P6-T011-I01 — SGT Linked-Route Fill Runtime Gate

## Objective

Validate the second linked Stock Connect route during market hours:

> one normal-OMS .SGT simulation order uses fresh exact-symbol tick evidence, remains bound to the pinned STOCK OMS identity, carries SHENGANGTONG route metadata, and converges to broker-evidence-backed FILLED exactly once.

## Preconditions

- guojin_sim build p5-simulation-calibration-8;
- SHENGANGTONG capability DETECTED;
- fresh exact .SGT tick from snapshot_tick_refresh for a calibrated five-digit symbol;
- no unresolved UNKNOWN/MANUAL_REVIEW.

## Scenario

Use one marketable LIMIT order, quantity <= 100, through normal Risk -> OMS -> QMT. Record exact client ID, token, frame digest, broker order ID, trade ID, route account type/fingerprint, callback/query evidence and final cumulative fill.

## Pass criteria

- exactly one successful .SGT submit;
- pinned STOCK OMS fingerprint remains authority;
- route_account_type=SHENGANGTONG when supplied by query evidence;
- FULL_FILL reaches original quantity exactly once;
- duplicate ORDER/DEAL/query facts do not double-count;
- no duplicate submit, blind retry or unresolved UNKNOWN;
- production/Galaxy/generic mutation = 0.

## Mutation budget

guojin_sim submit <= 2
guojin_sim cancel <= 1 cleanup only
production mutation = 0

## Scope lock

Runtime evidence only. If current Risk does not support .SGT, treat a deterministic pre-broker Risk rejection as a discovered prerequisite and stop; do not widen Risk on main inside this runtime task.
