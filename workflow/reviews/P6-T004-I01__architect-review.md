---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I01
task_key: P6-T004-I01
review_of: workflow/reports/P6-T004-I01__implementation-report.md
task_file: workflow/tasks/P6-T004-I01__guojin-sim-single-writer-execution-loop.md
status: CHANGES_REQUIRED
owner: architect
---

# P6-T004-I01 Architect Review

## 1. Gate verdict

**CHANGES_REQUIRED**

## 2. Reviewed commits

- Task base: `eb7c1ea913f1a063693b14464b9786772d1b6eca`
- Agent implementation: `eb27867af04160b3ccbc97d91e6405491e2be2ab`
- Agent handoff: `2e680283ac30d0de18592238ed82b66515fae445`

GitHub Actions for the handoff are green, including the new
`GuojinSimDispatchRecovery.tla` TLC model. The remaining findings are implementation/model
coverage gaps that are not exercised by those checks.

## 3. Findings

### F1 — BLOCKING: submit reservation can be stranded before a dispatch plan exists

Current `execute_intent()` performs these as separate transactions:

1. `create_intent()`;
2. `record_risk_decision()`;
3. `prepare_submit()` -> durable `SUBMITTING + submit_call_started=1`;
4. `_persist_dispatch()` -> first `qmt_execution_dispatches` row.

A process crash after step 3 and before step 4 leaves a durable order in `SUBMITTING` with
`submit_call_started=1`, but there is no dispatch row and no spool command.

On restart, `GuojinSimOmsRuntime.__init__()` calls `recover_dispatches()`, which scans only
`qmt_execution_dispatches`. Therefore this orphan is not recovered, aborted or escalated. It can
remain permanently stranded.

This is exactly a pre-dispatch crash window that the task required to close.

### F2 — BLOCKING: cancel has the same stranded-reservation window

`cancel_intent()` performs:

1. `prepare_cancel()` -> durable `CANCEL_PENDING + cancel_call_started=1`;
2. build cancel frame;
3. `_persist_dispatch()`.

A crash between 1 and 3 leaves `CANCEL_PENDING` with no cancel dispatch row. The current
`recover_dispatches()` cannot see or resolve it.

No automatic second cancel is allowed, but silently leaving the order stranded is also not an
acceptable recovery policy.

### F3 — BLOCKING: expired PLANNED dispatch does not fail closed cleanly

For `dispatch_state=PLANNED` and no active spool file, `_recover_dispatch()` calls
`QmtCommandSpool.publish(command)`.

`publish()` rejects an expired frame. Thus a legitimate crash after plan commit but before
publication, followed by restart after the command TTL/intent expiry, raises during startup rather
than durably converging the order/dispatch to a safe terminal or manual-review state.

Submit frames inherit the intent expiry; cancel frames use a 30-second TTL, so this is a realistic
restart boundary.

### F4 — COVERAGE: formal model begins after the missing reservation boundary

The new TLC model starts at `plan=NONE` and then `PersistPlan`; it does not model the durable
OMS reservation states (`RISK_ACCEPTED/SUBMITTING/CANCEL_PENDING`) that can exist before the
dispatch plan is committed. Therefore TLC success does not cover F1/F2.

## 4. What is accepted from I01

The following parts are retained and should not be redesigned:

- single Host-owned OMS writer / singleton leader;
- deterministic submit and cancel command identity;
- risk evaluated inside the public simulation execution API;
- command_result remains control-plane only;
- BrokerEvidence owns ACK/FILL/CANCEL/REJECT lifecycle;
- known inbox/claimed/processed/unknown frame adoption;
- conflicting immutable frame fail-close;
- production Guojin/Galaxy/generic mutation remains zero.

## 5. Required fix

Create one durable invariant:

> Any durable OMS state that reserves a submit/cancel side effect must either have a matching
> immutable dispatch plan in the same atomic SQLite commit, or have an explicit deterministic
> recovery policy that proves zero broker crossing and safely aborts/escalates without publishing.

Preferred implementation is to make reservation + dispatch-plan creation atomic under the same
Host leader transaction. If that requires repository `*_in_tx` helpers, add narrow helpers rather
than bypassing the write guard.

Also add startup repair/validation for legacy or fault-injected rows so impossible
`SUBMITTING/CANCEL_PENDING without dispatch` states fail closed instead of remaining invisible.

Expired pre-publication plans must converge without QMT publication.

## 6. Decision

Keep task `P6-T004`; create iteration `I02`. Do not start a new phase/task number.

No production authority is granted.
