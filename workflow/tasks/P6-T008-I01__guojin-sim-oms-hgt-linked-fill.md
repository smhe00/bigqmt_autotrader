---
workflow_schema: 1
phase: P6
task_id: P6-T008
iteration: I01
task_key: P6-T008-I01
state: AGENT_READY
owner: agent
audit_base_commit: cdf9a18cf59f255c719c2c1b4dd90e70820e852b
expected_report: workflow/reports/P6-T008-I01__implementation-report.md
expected_review: workflow/reviews/P6-T008-I01__architect-review.md
---

# P6-T008-I01 — Guojin Simulation OMS HGT Linked-Route Fill Gate

## Objective

Validate one invariant only:

> one OMS-owned `.HGT` simulation order can traverse the linked Hong Kong Connect route and
> converge to broker-evidence-backed `FILLED` without weakening account/session/token identity.

This must use the normal OMS execution API, not the diagnostic simulation probe.

## Authority

Only the existing Guojin simulation instance:

```text
terminal_instance_id = guojin_sim
execution_mode = SIMULATION_CALIBRATION
simulation_only = true
bridge_build = p5-simulation-calibration-7
bound OMS account type = STOCK
```

The linked route may be `HUGANGTONG` in active-query evidence, but it must remain bound to the
same authorized simulation account/fingerprint. Do not create or infer a second account authority.

Production Guojin, Galaxy, generic deployment and LIVE_CANARY mutation remain forbidden.

## Runtime

Use a valid Hong Kong Connect trading window available to the simulation terminal.

Choose one previously calibrated five-digit `.HGT` symbol with valid instrument/tick evidence,
preferably one from the existing bounded discovery set. Choose side, quantity <= 100 and LIMIT price
needed for a marketable fill.

The Agent may make these choices autonomously inside `guojin_sim`.

## Preflight

Verify before mutation:

1. exact `guojin_sim` manifest/session/build/fingerprint;
2. Host started with simulation mutation authorization;
3. OMS leader held;
4. exact `.HGT` instrument detail and fresh tick available;
5. active route evidence identifies the linked route consistently;
6. no unresolved UNKNOWN/MANUAL_REVIEW from prior work;
7. production/Galaxy/generic command roots remain untouched.

## Required evidence

Record:

- chosen `.HGT` symbol, side, quantity, LIMIT price and quote;
- client_order_id;
- deterministic Risk decision;
- immutable submit command ID/token/frame digest;
- broker order ID;
- callback ORDER/DEAL raw identity/status;
- active-query route_account_type and route_account_fingerprint where available;
- BrokerEvidence type(s);
- exact OMS lifecycle and cumulative fill;
- duplicate/semantic-duplicate handling;
- mutation accounting.

The route account metadata must not replace the pinned OMS account identity.

## Pass criteria

PASS candidate requires:

1. exactly one `.HGT` simulation submit;
2. same pinned simulation account fingerprint throughout;
3. linked route evidence is admitted with the expected route metadata;
4. exact token and broker order ID remain consistent;
5. broker evidence converges OMS to `FILLED`;
6. cumulative fill equals original quantity exactly once;
7. no duplicate submit or blind retry;
8. no unresolved UNKNOWN;
9. production/Galaxy/generic mutation = 0.

## Mutation budget

```text
guojin_sim submits = max 2
guojin_sim cancels = max 1 cleanup only if a bounded accepted order does not fill
production mutation = 0
```

A second submit is allowed only after a proven clean pre-broker rejection or known terminal broker
rejection. Never retry after UNKNOWN or ambiguous crossing.

If the first order remains resting, clean it up once through the OMS exact-cancel path before any
alternate attempt.

## Scope lock

Do not add SGT, restart soak, partial-fill engineering or unrelated code to I01.

If linked-route execution exposes a distinct defect, preserve evidence and create the next small
iteration rather than widening this one.

## Report

Update only `workflow/reports/P6-T008-I01__implementation-report.md`, then hand back
`REVIEW_READY`.
