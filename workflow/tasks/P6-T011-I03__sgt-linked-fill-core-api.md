---
workflow_schema: 1
phase: P6
task_id: P6-T011
iteration: I03
task_key: P6-T011-I03
state: CHANGES_REQUIRED
owner: agent
audit_base_commit: 114ee09ebb7702cdad72ebb16308e44d4a197e5c
expected_report: workflow/reports/P6-T011-I03__implementation-report.md
expected_review: workflow/reviews/P6-T011-I03__architect-review.md
---

# P6-T011-I03 — SGT Linked-Route Fill on Execution Core API

## Objective

Validate the current post-P7 `main` runtime path:

> one structurally valid `.SGT` OrderIntent submitted through the strictly pinned `guojin_sim` Execution Core path must traverse the SHENGANGTONG linked route and converge to broker-evidence-backed `FILLED` exactly once.

This is a **runtime validation task only**. Do not reintroduce Risk into Core.

## Current API baseline

Use current `main` at or after:

`114ee09ebb7702cdad72ebb16308e44d4a197e5c`

The simulation execution API is now:

```python
GuojinSimOmsRuntime.execute_intent(intent)
```

Do **not** construct or pass:

- `RiskSnapshot`
- `RiskPolicy`
- Production Runtime health/telemetry objects

The Core path creates a deterministic durable execution authorization with:

```text
rule_version = guojin-sim-accept-all-v1
```

The historical database field/type name `RiskDecision` remains for durable compatibility, but in this Core path it is **execution authorization**, not Production Risk policy evaluation.

## Safety boundaries that remain mandatory

- exact terminal instance = `guojin_sim`;
- `execution_mode = SIMULATION_CALIBRATION`;
- `simulation_only = true`;
- authorized pinned STOCK account fingerprint;
- bridge build = `p5-simulation-calibration-8`;
- valid typed `OrderIntent`;
- intent account fingerprint must match the pinned simulator;
- immutable dispatch identity;
- exact command/frame digest;
- broker token identity;
- no blind retry;
- broker evidence is the only lifecycle authority;
- production Guojin/Galaxy/generic mutation remains zero.

P7 changed software layering only. It did not broaden mutation authority.

## Runtime preflight

Before any mutation:

1. `git fetch origin && git pull --ff-only origin main`;
2. confirm HEAD contains P7 merge `114ee09ebb7702cdad72ebb16308e44d4a197e5c` or a later descendant;
3. run `python tools/verify_workflow_contract.py`;
4. confirm exact `guojin_sim` manifest/session/build/account fingerprint;
5. confirm no unresolved `UNKNOWN` / `MANUAL_REVIEW`;
6. obtain a **fresh exact-symbol tick** for the chosen five-digit `.SGT` symbol;
7. confirm the route evidence identifies SHENGANGTONG for the linked route;
8. confirm production roots are untouched.

If any identity/session/build/tick/route prerequisite is ambiguous, stop before broker mutation and report BLOCKED evidence.

## Scenario

Construct one typed `OrderIntent` using a calibrated five-digit `.SGT` symbol.

Use:

```text
OrderIntent
 -> GuojinSimOmsRuntime.execute_intent(intent)
 -> Core durable execution authorization
 -> atomic OMS dispatch
 -> QMT simulation mutation
 -> ORDER / DEAL / active-query BrokerEvidence
 -> FILLED
```

Choose side/quantity autonomously within the simulation task constraints; quantity must be <= 100.

Prefer a marketable LIMIT order when the simulation market window and current quote make that appropriate.

Do not manufacture positions. Do not use any production authority.

## Required evidence

Record exact values for:

- `main` HEAD used;
- terminal instance/session/build/account fingerprint;
- symbol / side / qty / limit;
- fresh exact quote and quote timestamp;
- client_order_id;
- durable execution authorization:
  - accepted;
  - `rule_version = guojin-sim-accept-all-v1`;
- immutable command_id;
- broker token / m_strRemark identity;
- frame digest;
- broker_order_id;
- ORDER raw status/substatus;
- DEAL raw evidence when available;
- active-query evidence;
- `route_account_type = SHENGANGTONG` when supplied;
- route account fingerprint;
- pinned STOCK OMS fingerprint;
- complete OMS lifecycle;
- cumulative fill quantity;
- duplicate evidence handling;
- mutation counts.

## Exactly-once / idempotency requirements

Prove:

1. exactly one successful submit identity crossed the `guojin_sim` broker boundary;
2. duplicate ORDER/DEAL/query evidence does not double-count fill;
3. cumulative fill never exceeds original quantity;
4. no blind retry occurred;
5. no unresolved `UNKNOWN` remains at PASS;
6. terminal conflict would fail closed rather than being guessed.

## Mutation budget

- `guojin_sim` submit <= 2;
- `guojin_sim` cancel <= 1, cleanup only;
- production Guojin submit/cancel = 0;
- Galaxy submit/cancel = 0;
- generic production submit/cancel = 0.

A second simulation submit is permitted only after a proven pre-broker/local rejection or a known terminal broker rejection. Never retry after an ambiguous broker crossing.

## Scope lock

Runtime validation only.

Do not modify:

- Core/Runtime architecture;
- Risk engine;
- OMS state machine;
- broker evidence mapper;
- QMT bridge mutation semantics;
- production authority.

If a new independent code defect appears, preserve evidence, do not widen this task, and hand it back for a new narrow iteration.

## Required verification

Before handoff:

```bash
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/audit_side_effect_calls.py
```

Run targeted runtime/OMS tests relevant to the evidence path and record exact results.

## Exit criteria

PASS candidate requires all of:

- current post-P7 Core-only invocation used;
- fresh SGT linked-route evidence;
- SHENGANGTONG route coherent with pinned STOCK authority;
- BrokerEvidence-backed FILLED;
- exactly-once fill convergence;
- no unresolved UNKNOWN/MANUAL_REVIEW;
- mutation budget respected;
- production/Galaxy/generic mutation = 0.

Then complete the matched implementation report and perform the standard Agent -> Architect handoff.
