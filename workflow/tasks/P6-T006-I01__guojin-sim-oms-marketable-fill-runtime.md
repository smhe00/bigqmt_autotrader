---
workflow_schema: 1
phase: P6
task_id: P6-T006
iteration: I01
task_key: P6-T006-I01
state: AGENT_READY
owner: agent
audit_base_commit: aa99bd38bf5e6a75dabde11a33ee2dccd10b18ef
expected_report: workflow/reports/P6-T006-I01__implementation-report.md
expected_review: workflow/reviews/P6-T006-I01__architect-review.md
---

# P6-T006-I01 — Guojin Simulation OMS Marketable Fill Runtime Gate

## Objective

Validate exactly one OMS-owned **marketable** simulation order through the normal execution path:

```text
OrderIntent
  -> Risk ACCEPT
  -> atomic OMS dispatch
  -> guojin_sim
  -> ORDER/DEAL BrokerEvidence
  -> OMS FILLED
```

This task validates one invariant only:

> one marketable OMS-owned simulation order can reach broker-evidence-backed FILLED exactly once.

Do not include cancel, restart soak, partial-fill engineering, HGT/SGT or production live trading.

## Authority

Only:

```text
terminal_instance_id = guojin_sim
execution_mode = SIMULATION_CALIBRATION
simulation_only = true
bridge_build = p5-simulation-calibration-7
```

Production `guojin`, Galaxy, generic deployment and LIVE_CANARY mutation remain forbidden.

## Runtime

Use a valid A-share market session.

Choose one liquid simulation-supported A-share/ETF, side, quantity <= 100 and a valid LIMIT price
that is expected to be marketable under the current quote.

The Agent may autonomously select the exact symbol/side/price inside `guojin_sim`; no user
confirmation is required.

## Preflight

Before mutation verify:

1. exact `guojin_sim` manifest/session/build/fingerprint;
2. Host `--allow-simulation-mutation`;
3. OMS leader held;
4. fresh quote for the chosen instrument;
5. no unresolved UNKNOWN/MANUAL_REVIEW from a previous attempt;
6. production/Galaxy/generic mutation roots remain untouched.

## Required evidence

Record:

- chosen symbol/side/quantity/price and pre-submit quote;
- client_order_id;
- Risk decision;
- immutable submit command ID/token/frame digest;
- command spool state;
- broker_order_id;
- ORDER callback/query raw status;
- DEAL callback/query trade ID and quantity if present;
- BrokerEvidence type(s);
- exact OMS lifecycle sequence;
- duplicate/semantic-duplicate observations;
- mutation accounting.

`command_result` must remain control-plane only and cannot be used as fill truth.

## Pass criteria

PASS candidate requires:

1. exactly one simulation submit;
2. broker evidence converges the order to `FILLED`;
3. cumulative filled quantity equals the original order quantity;
4. no second submit caused by callback/query lag or restart logic;
5. duplicate ORDER/DEAL/query evidence does not double-count fill;
6. no unresolved UNKNOWN;
7. production Guojin/Galaxy/generic mutation = 0.

## Mutation budget

```text
guojin_sim submit commands: max 2
guojin_sim cancel commands: 0
production mutation: 0
```

A second submit is permitted only after a proven clean pre-broker/local rejection or a known
terminal broker rejection with no ambiguity. Never retry after UNKNOWN.

## Scope lock

Do not add unrelated code/features.

If the marketable-fill scenario exposes a distinct implementation defect, preserve the evidence and
create the next small iteration rather than widening I01.

No restart validation belongs in this task.

## Verification / report

After runtime, run the existing verification suite. Update only:

```text
workflow/reports/P6-T006-I01__implementation-report.md
```

Then hand back `REVIEW_READY`.
