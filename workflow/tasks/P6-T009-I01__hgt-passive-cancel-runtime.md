---
workflow_schema: 1
phase: P6
task_id: P6-T009
iteration: I01
task_key: P6-T009-I01
state: AGENT_READY
owner: agent
audit_base_commit: d3fb18ed45f4ff2ac0b68db396301999288bb0b1
expected_report: workflow/reports/P6-T009-I01__implementation-report.md
expected_review: workflow/reviews/P6-T009-I01__architect-review.md
---

# P6-T009-I01 — HGT Passive ACK + Exact Cancel Runtime Gate

## Objective

Validate one HGT cancel-path invariant during the live market window:

> one OMS-owned passive 00700.HGT simulation order reaches broker-evidence-backed ACKNOWLEDGED on the linked HUGANGTONG route, then one exact OMS-owned cancel converges it to CANCELLED.

## Preconditions

- guojin_sim build p5-simulation-calibration-8;
- fresh exact 00700.HGT tick from snapshot_tick_refresh;
- pinned STOCK OMS fingerprint healthy;
- HUGANGTONG route capability detected;
- no unresolved UNKNOWN/MANUAL_REVIEW.

## Scenario

1. use normal OMS API;
2. SELL 100 00700.HGT or another calibrated HGT symbol at a clearly passive valid LIMIT price;
3. require ORDER_ACCEPTED -> ACKNOWLEDGED from BrokerEvidence;
4. verify linked HUGANGTONG route metadata and exact broker token/order ID;
5. issue exactly one OMS-owned cancel;
6. require broker ORDER_CANCELLED -> OMS CANCELLED.

## Pass criteria

- exactly one submit and one cancel;
- same client/token/broker_order_id throughout;
- route metadata never replaces pinned STOCK authority;
- command_result never acts as broker lifecycle truth;
- no duplicate submit/cancel, no unresolved UNKNOWN;
- production Guojin/Galaxy/generic mutation = 0.

## Mutation budget

guojin_sim submit <= 1
guojin_sim cancel <= 1
production mutation = 0

## Scope lock

Runtime evidence only. Do not add SGT, restart, production LIVE_CANARY or unrelated code. If a code defect is discovered, preserve evidence and stop this task for Architect triage.
