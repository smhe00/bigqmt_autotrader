---
workflow_schema: 1
phase: P6
task_id: P6-T005
iteration: I01
task_key: P6-T005-I01
state: AGENT_READY
owner: agent
audit_base_commit: cc04a99e18ac93b12e77f1083743258c29b5878a
expected_report: workflow/reports/P6-T005-I01__implementation-report.md
expected_review: workflow/reviews/P6-T005-I01__architect-review.md
---

# P6-T005-I01 — Guojin Simulation OMS Passive Submit/Cancel Runtime Gate

## Objective

Validate exactly one market-hours end-to-end lifecycle through the repaired OMS-owned execution path:

```text
OrderIntent
  -> deterministic Risk ACCEPT
  -> atomic OMS submit reservation + immutable dispatch plan
  -> QMT command spool
  -> guojin_sim broker mutation
  -> ORDER/active-query BrokerEvidence
  -> OMS ACKNOWLEDGED
  -> OMS-owned exact-token cancel
  -> ORDER/active-query BrokerEvidence
  -> OMS CANCELLED
```

This task is intentionally narrow. It does **not** include fill testing, HGT/SGT, restart soak,
partial-fill, production live trading, or new feature work.

## Runtime window

Use the next valid A-share market session, preferably:

```text
2026-09-22 Asia/Shanghai
09:15-09:29 read-only preflight
09:30 onward runtime mutation
```

If the local Agent starts later, any valid A-share market window is acceptable.

## Exact authority

Only the existing simulation instance is authorized:

```text
TERMINAL_INSTANCE_ID = guojin_sim
EXECUTION_MODE = SIMULATION_CALIBRATION
SIMULATION_ONLY = True
BRIDGE_BUILD = p5-simulation-calibration-7
```

The Agent may autonomously choose one liquid simulation-supported A-share or ETF, side, quantity
and LIMIT price needed to create a passive accepted order, subject to existing bridge/broker rules.

No per-order user confirmation is required inside `guojin_sim`.

## Hard prohibition

Never mutate:

- production `guojin`;
- Galaxy;
- generic deployment;
- LIVE_CANARY;
- any real-money account.

If production identity is observed, stop mutation immediately and collect read-only diagnostics only.

## Scope lock

This iteration validates **one invariant only**:

> one OMS-owned passive submit can reach broker ACK and then one OMS-owned exact cancel can converge
> to CANCELLED without duplicate broker mutation.

Do not add unrelated code/features unless a runtime defect directly blocks this invariant.

If a distinct defect is found, preserve evidence and create the next small iteration rather than
widening this one.

## Preflight

Before publishing any mutation verify:

1. QMT is logged into the pinned Guojin simulation account;
2. current session/build/fingerprint exactly match the authorized manifest;
3. Host is started with `--allow-simulation-mutation`;
4. Host owns the OMS leader lease;
5. no unresolved UNKNOWN/MANUAL_REVIEW from a prior runtime attempt;
6. fresh market data is available for the chosen symbol;
7. production/Galaxy/generic instances remain mutation-free.

## Scenario

### S1 — passive submit -> ACK

Use the **new OMS execution API**, not `simulation_probe` as the primary submit path.

Choose one liquid supported A-share/ETF and a valid passive LIMIT price.

Required evidence:

- client_order_id;
- risk decision;
- command_id;
- broker_token;
- exact immutable dispatch frame digest;
- spool transition;
- broker_order_id;
- raw ORDER/query status;
- BrokerEvidence;
- OMS state sequence.

The accepted lifecycle must be broker-evidence driven. `command_result` alone is not ACK.

### S2 — exact OMS-owned cancel -> CANCELLED

After exact broker ACK is known:

- invoke the OMS-owned cancel path;
- broker_order_id/token must come from trusted persistent state;
- publish at most one exact cancel command for that order;
- reconcile ORDER/query evidence to `CANCELLED`.

Do not issue a second cancel merely because query state lags.

## Mutation budget

```text
new simulation submit commands: max 3
simulation cancel commands: max 2
production mutation: 0
```

The extra bounded attempt is only for a clean pre-broker rejection or unsupported simulation symbol.
Never retry after UNKNOWN or ambiguous broker crossing.

## Pass criteria

PASS candidate requires all of:

1. one `guojin_sim` order reaches broker-evidence-backed ACKNOWLEDGED;
2. one OMS-owned exact cancel is issued;
3. broker evidence converges that order to CANCELLED;
4. submit command identity is deterministic;
5. no duplicate submit/cancel broker mutation is observed;
6. `command_result` is not used as broker lifecycle truth;
7. no unresolved UNKNOWN;
8. production/Galaxy/generic mutation count = 0;
9. complete evidence is recorded in the report.

## Failure policy

- clean local/pre-broker reject: one bounded alternate case allowed;
- known broker reject: reconcile first, then one alternate case allowed;
- UNKNOWN after possible broker crossing: stop new mutation and do read-only reconciliation;
- identity mismatch / duplicate mutation / ambiguous active order: stop mutation;
- production exposure: immediate stop.

## Verification

After runtime evidence collection run the existing repository verification suite and CI.

No new formal model is required unless code changes alter dispatch/recovery semantics.

## Report

Update only:

```text
workflow/reports/P6-T005-I01__implementation-report.md
```

Include:

- exact local runtime time/session/build;
- chosen symbol/side/qty/price;
- risk decision;
- command/token/broker-order identities;
- raw broker status/query observations;
- BrokerEvidence and OMS transitions;
- submit/cancel mutation counts;
- duplicate/retry evidence;
- production/Galaxy/generic mutation = 0;
- any code fix and its regression test;
- final CI result.

When complete, hand back `REVIEW_READY`.
