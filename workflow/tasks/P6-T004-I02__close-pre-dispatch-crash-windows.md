---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I02
task_key: P6-T004-I02
state: CHANGES_REQUIRED
owner: agent
audit_base_commit: 2e680283ac30d0de18592238ed82b66515fae445
expected_report: workflow/reports/P6-T004-I02__implementation-report.md
expected_review: workflow/reviews/P6-T004-I02__architect-review.md
---

# P6-T004-I02 — Close Pre-Dispatch Crash Windows

## Objective

Fix only the crash/recovery gaps identified in the I01 Architect review while preserving the
accepted single-writer simulation execution architecture.

No production authority change is allowed.

## Required invariant

For both SUBMIT and CANCEL:

```text
side-effect reservation durable
        =>
matching immutable dispatch plan durable in the same atomic SQLite commit
OR
explicit startup recovery proves no broker crossing and converges fail-closed
```

There must be no durable `SUBMITTING` / `CANCEL_PENDING` reservation that is invisible to
recovery.

## A. Atomic submit reservation + dispatch plan

Refactor the accepted-risk submit path so that the transition/reservation to `SUBMITTING` and
creation of the immutable `qmt_execution_dispatches` PLANNED row are one SQLite transaction under
the current Host leader lease.

Requirements:

- no filesystem publication inside the SQLite transaction;
- immutable frame bytes/digest/command_id already determined before commit;
- write guard/fencing is checked inside the transaction;
- duplicate/conflicting client/command identity still fails closed;
- after transaction commit, only the existing deterministic outbox recovery publishes the frame.

If a crash occurs before that transaction commits: no submit reservation and no dispatch plan may
remain.

If a crash occurs after commit: a PLANNED dispatch exists and is recoverable.

## B. Atomic cancel reservation + dispatch plan

Apply the same rule to cancel:

- trusted persistent broker_order_id/token first;
- `CANCEL_PENDING + cancel_call_started` and immutable cancel dispatch plan in one transaction;
- no broker/filesystem call inside that transaction;
- duplicate cancel remains idempotent;
- no stranded CANCEL_PENDING without dispatch.

## C. Startup invariant sweep

At runtime startup, before allowing new execution:

Detect impossible/legacy/fault-injected rows such as:

- `SUBMITTING` with `submit_call_started=1` but no matching submit dispatch;
- `CANCEL_PENDING` / unresolved cancel reservation with no matching cancel dispatch;
- dispatch row whose order/client/account/session identity conflicts with OMS state.

Do not guess or auto-publish in these cases.

Converge to a safe explicit state (normally MANUAL_REVIEW) or fail startup closed, with a durable
reason/event. Choose one consistent policy and test it.

Do not turn these cases into automatic retry.

## D. Expired pre-publication plan

For a PLANNED dispatch with no known spool copy:

- if the command is still valid and exact absence is provable under the current command-spool
  retention contract, deterministic publication is allowed;
- if the command is expired, publish **nothing** and durably converge to a safe state;
- no expired command exception may leave Host startup half-initialized.

For submit, preserve risk/intent semantics; for cancel, preserve the underlying broker lifecycle
without fabricating cancellation.

## E. Absence/history contract

Make the assumption behind "exact absence" explicit and machine-tested.

Current `QmtCommandSpool.locate()` only covers:
`inbox/claimed/processed/rejected/unknown`.

Either:

1. formally establish that command files in these states are never archived/deleted by repository
   runtime before the dispatch record is closed, and add a regression/static invariant; or
2. extend durable history lookup so archived/retained command history participates in absence
   proof.

Do not treat "not found in active directories" as proof if the repository can legitimately move
that command elsewhere.

## F. Failure-injection tests

Add explicit tests for at least:

1. crash before atomic submit reservation/plan commit -> neither survives;
2. crash immediately after atomic submit reservation/plan commit -> PLANNED exists and recovers;
3. fault-injected SUBMITTING-without-dispatch -> startup fail-close/manual-review;
4. crash before atomic cancel reservation/plan commit -> neither cancel reservation nor plan survives;
5. crash immediately after atomic cancel reservation/plan commit -> PLANNED cancel recovers once;
6. fault-injected CANCEL_PENDING-without-dispatch -> fail-close/manual-review;
7. expired PLANNED submit -> zero publication + safe convergence;
8. expired PLANNED cancel -> zero publication + safe convergence;
9. existing inbox/claimed/processed/unknown exact frame -> no duplicate publication;
10. conflicting frame -> fail closed;
11. second leader remains fenced;
12. risk-rejected intent still creates zero command.

Tests must check both database state and command-spool mutation count.

## G. Formal model

Extend `GuojinSimDispatchRecovery.tla` (or add a tightly scoped model) to include the
pre-dispatch reservation boundary.

The model must represent at least:

- risk accepted / cancellable broker state;
- side-effect reservation;
- dispatch plan existence;
- spool state;
- crash/restart;
- expiry;
- manual-review/fail-close.

Required safety invariants:

- reservation implies dispatch plan, except explicit safe terminal/manual-review recovery state;
- broker side-effect count <= 1;
- UNKNOWN never republishes;
- expired PLANNED never publishes;
- restart cannot strand a reserved side effect invisibly.

Add it to mandatory CI TLC.

## H. Scope boundary

Retain all I01 safety constraints:

- only `guojin_sim`;
- `SIMULATION_CALIBRATION`;
- `SIMULATION_ONLY=true`;
- exact fingerprint/build/current session;
- explicit `--allow-simulation-mutation`;
- Host leader held;
- production Guojin/Galaxy/generic mutation = 0;
- no LIVE_CANARY change.

No real broker mutation is required for I02. This is a crash-safety repair.

## Verification

Run:

```bash
python tools/verify_workflow_contract.py
pytest -q
python tools/audit_side_effect_calls.py
python tools/build_qmt_deployments.py --check
python tools/verify_bridge_protocol_exhaustive.py
python tools/verify_bridge_schema_contract.py
python tools/verify_broker_evidence_contract.py
```

and the updated/new TLC model in CI.

## Report

Update only `workflow/reports/P6-T004-I02__implementation-report.md`.

Include:

- exact transaction boundary before/after fix;
- startup invariant-sweep behavior;
- expired-plan behavior;
- absence/history contract;
- fault-injection matrix;
- formal invariant/results;
- all CI results;
- explicit zero broker mutation during I02;
- remaining runtime validation requirement, if any.

When complete, use `tools/agent_workflow_handoff.py`. Do not edit Architect review or create the
next task.
