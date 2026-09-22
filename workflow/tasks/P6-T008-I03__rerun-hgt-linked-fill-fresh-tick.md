---
workflow_schema: 1
phase: P6
task_id: P6-T008
iteration: I03
task_key: P6-T008-I03
state: AGENT_READY
owner: agent
audit_base_commit: ca0b76992fa82e936ef8a690853761dcfd69f289
expected_report: workflow/reports/P6-T008-I03__implementation-report.md
expected_review: workflow/reviews/P6-T008-I03__architect-review.md
---

# P6-T008-I03 — Rerun HGT Linked-Route Fill with Fresh Runtime Tick

## Objective

Rerun the original HGT linked-route fill invariant after deploying the runtime tick refresh:

> one OMS-owned .HGT simulation order uses fresh exact-symbol tick evidence, traverses the linked HUGANGTONG route, and converges to broker-evidence-backed FILLED without weakening the pinned STOCK OMS identity.

## Mandatory deployment precondition

Before any mutation:

1. pull current main;
2. deploy/reload qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py;
3. manifest must report bridge_build = p5-simulation-calibration-8;
4. terminal_instance_id = guojin_sim;
5. execution_mode = SIMULATION_CALIBRATION;
6. simulation_only = true;
7. pinned STOCK OMS fingerprint must match the authorized simulation fingerprint.

If the running terminal still reports build 7, do not submit.

## Fresh tick preflight

Use a Host REQUEST_SNAPSHOT after build-8 is running.

Require a newly emitted instrument_tick_capabilities event from source snapshot_tick_refresh for the chosen .HGT symbol.

Before mutation prove:

- exact requested/reported symbol match;
- positive last_price;
- broker tick_time belongs to the current trading session and satisfies the local freshness threshold;
- local observation timestamp is current;
- HUGANGTONG route capability is DETECTED;
- route fingerprint is present but remains metadata subordinate to the pinned STOCK OMS fingerprint.

Do not use position last_price as tick evidence.

## Runtime scenario

Choose one calibrated .HGT symbol with fresh evidence, preferably 00700.HGT if still valid.

Use the normal OMS API and a marketable LIMIT order with quantity <= 100.

Required path:

OrderIntent -> Risk ACCEPT -> atomic OMS dispatch -> guojin_sim -> ORDER/DEAL/query BrokerEvidence -> FILLED.

## Identity requirements

Record and verify:

- client_order_id;
- immutable command ID;
- broker token;
- frame digest;
- broker_order_id;
- trade_id where present;
- pinned OMS account fingerprint;
- route_account_type = HUGANGTONG where active-query evidence supplies it;
- route_account_fingerprint;
- exact OMS lifecycle and cumulative fill.

The linked route must never replace the pinned OMS account identity.

## Mutation budget

guojin_sim submits <= 2
guojin_sim cancels <= 1 cleanup only
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0

A second submit is allowed only after a proven clean pre-broker/local rejection or known terminal broker rejection. Never retry after UNKNOWN.

## Pass criteria

1. build-8 fresh exact tick is demonstrated before submit;
2. exactly one successful HGT order identity reaches broker evidence;
3. linked route metadata is coherent;
4. FILLED cumulative quantity equals original quantity exactly once;
5. duplicate callback/query facts do not double-count;
6. no unresolved UNKNOWN;
7. no duplicate submit;
8. production/Galaxy/generic mutation = 0.

## Scope lock

Only HGT linked-route fill. Do not add SGT, restart or partial-fill engineering.

If the market window closes before a safe attempt, preserve build-8 fresh-tick evidence and report the runtime gate as window-blocked; do not force a trade outside the valid window.

## Handoff

Update the matching implementation report and return REVIEW_READY.
