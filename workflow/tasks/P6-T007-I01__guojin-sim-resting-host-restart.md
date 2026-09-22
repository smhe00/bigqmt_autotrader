---
workflow_schema: 1
phase: P6
task_id: P6-T007
iteration: I01
task_key: P6-T007-I01
state: AGENT_READY
owner: agent
audit_base_commit: dbe48c0e77eadb3b85c6d4fd8c0a348baf4fcd05
expected_report: workflow/reports/P6-T007-I01__implementation-report.md
expected_review: workflow/reviews/P6-T007-I01__architect-review.md
---

# P6-T007-I01 — Guojin Simulation Resting Order Host-Restart Gate

## Objective

Validate one invariant only:

> a broker-ACKed resting `guojin_sim` order survives Host restart with durable identity/state,
> zero duplicate submit, and can then be cleanly cancelled once.

## Runtime sequence

During a valid A-share trading window:

1. create one passive OMS-owned LIMIT order through the normal Risk -> OMS path;
2. wait for broker-evidence-backed `ACKNOWLEDGED`;
3. record submit command ID/token/broker_order_id and spool state;
4. stop the simulation Host cleanly;
5. restart Host against the same `guojin_sim` instance/session if still current;
6. reconcile callback/query evidence;
7. prove no second SUBMIT_LIMIT command and no second broker submit;
8. confirm the order remains the same durable broker order;
9. use the OMS-owned exact cancel path once as cleanup;
10. reconcile to `CANCELLED`.

## Authority

Only `guojin_sim / SIMULATION_CALIBRATION / simulation_only=true`.

Production Guojin, Galaxy, generic and LIVE_CANARY mutation remain forbidden.

## Mutation budget

```text
guojin_sim submits = max 1
guojin_sim cancels = max 1
production mutation = 0
```

Never retry submit after UNKNOWN or ambiguous crossing.

## Required evidence

Record before and after restart:

- instance/session/build/fingerprint;
- client_order_id;
- submit command ID/token/frame digest;
- broker_order_id;
- OMS status;
- spool path/state;
- count of SUBMIT_LIMIT dispatch rows/files;
- count of broker submit mutations;
- mapper/durable identity restoration;
- post-restart active-query/callback evidence;
- exact cleanup cancel identity and final CANCELLED state.

## Pass criteria

PASS requires:

1. ACKNOWLEDGED before restart;
2. same client/token/broker_order_id after restart;
3. exactly one submit command and one broker submit total;
4. no automatic replay/resubmit;
5. post-restart evidence is admitted and converges normally;
6. exactly one cleanup cancel;
7. final OMS state CANCELLED;
8. zero unresolved UNKNOWN;
9. zero production/Galaxy/generic mutation.

## Scope lock

Do not add fill/partial-fill/HGT/SGT or unrelated code.

If restart exposes a distinct code defect, preserve evidence and create the next iteration; do not
widen this task.

## Report

Update only `workflow/reports/P6-T007-I01__implementation-report.md`, then hand back
`REVIEW_READY`.
