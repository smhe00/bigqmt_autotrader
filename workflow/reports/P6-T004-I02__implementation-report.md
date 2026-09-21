---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I02
task_key: P6-T004-I02
reply_to: workflow/tasks/P6-T004-I02__close-pre-dispatch-crash-windows.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T004-I02__architect-review.md
---

# P6-T004-I02 Implementation Report

## 1. Result

- Status: `REVIEW_READY`
- Base commit: `2b2acd6a0453d1a597fae63aceebe2b80cc6e9d2`
- Primary crash-window repair: `a869c4332cd09b46bdcbb822396b2dc910b4236f`
- Restart identity repair: `9f41d630e0f2a6043d93a0aff956777a123776d3`
- Test repair/final implementation commit: `56089e69a0a694332ad7d420b8f3f56874a776c4`
- GitHub Actions run: `35598923724` — **SUCCESS**

P6-T004-I02 closes the two blocking reservation-before-dispatch crash windows identified by
the Architect in I01. Submit and cancel reservation are now committed atomically with the exact
immutable QMT dispatch plan under the existing Host-owned OMS leader lease.

No broker/QMT mutation was executed during I02.

## 2. Atomic submit boundary

Before I02 the path was:

```text
RISK_ACCEPTED
  -> prepare_submit() commits SUBMITTING + submit_call_started=1
  -> _persist_dispatch() commits PLANNED
```

A crash between those commits could strand `SUBMITTING` with no dispatch record.

I02 adds repository `prepare_submit_in_tx()` and runtime
`_reserve_and_persist_dispatch(..., cancel=False)`.

The new durable sequence is:

```text
build immutable command frame
  -> BEGIN IMMEDIATE
     -> leader/write guard
     -> prepare_submit_in_tx()
     -> insert qmt_execution_dispatches(PLANNED, exact frame bytes/digest)
     -> COMMIT
  -> filesystem publication/recovery
```

Therefore reservation and dispatch-plan creation either both commit or both roll back.
Filesystem publication remains outside SQLite.

Failure injection verifies that an exception after dispatch-row insertion but before commit leaves:

```text
order status = RISK_ACCEPTED
submit_call_started = 0
dispatch rows = 0
spool files = 0
```

A crash immediately after the atomic commit leaves:

```text
order status = SUBMITTING
submit_call_started = 1
dispatch state = PLANNED
spool file = absent
```

and restart deterministically recovers that exact immutable plan.

## 3. Atomic cancel boundary

The same pattern was applied to cancel through `prepare_cancel_in_tx()`.

The new cancel path commits in one SQLite transaction:

```text
trusted persistent broker_order_id/token
  -> CANCEL_PENDING + cancel_call_started=1
  -> exact immutable CANCEL_ORDER dispatch plan
  -> COMMIT
  -> filesystem publication/recovery
```

Failure injection proves a pre-commit fault restores the prior broker lifecycle
(`ACKNOWLEDGED` in the test), leaves `cancel_call_started=0`, and creates no cancel dispatch.

A post-commit/pre-publish crash leaves one PLANNED cancel dispatch and restart publishes/adopts it
once without creating a second cancel identity.

## 4. Startup invariant sweep

`GuojinSimOmsRuntime.__init__()` now runs:

```text
restore persisted identities
refresh durable QMT identities
restore Host-owned dispatch-plan mapper identities
validate dispatch invariants
recover dispatches
```

The invariant sweep detects:

- `SUBMITTING + submit_call_started=1` without a matching current-session SUBMIT_LIMIT dispatch;
- unresolved cancel reservation / `CANCEL_PENDING` without a matching current-session
  CANCEL_ORDER dispatch.

These impossible/legacy/fault-injected states are moved durably to `MANUAL_REVIEW` with an
explicit event/reason. No command is published.

For cancel orphan repair, `cancel_outcome_resolved=1` is persisted because the absence of the
dispatch plan proves this local reservation cannot be replayed as an automatic cancel.

## 5. Expired pre-publication plans

For `PLANNED` + exact command absence:

- valid TTL -> deterministic publication remains allowed;
- expired TTL -> **zero publication**, dispatch becomes `MANUAL_REVIEW`, OMS order becomes
  `MANUAL_REVIEW`.

The runtime no longer lets `QmtCommandSpool.publish()` raise an expiry exception during startup
and leave Host initialization half-complete.

Both submit and cancel expired-plan cases have explicit regression tests using syntactically valid
but already-expired command frames.

## 6. Absence / retained-history contract

The exact-absence proof remains based on the command spool states:

```text
commands/inbox
commands/claimed
commands/processed
commands/rejected
commands/unknown
```

The repository event archiver operates on the event spool root
(`inbox/processed/quarantine/archive/checkpoints`) and does **not** archive/delete
`commands/*`.

A regression test creates a command-history file under `commands/processed`, invokes the
event-archiver discovery surface, and verifies the command file remains outside the archive set.

Therefore, under repository-managed runtime behavior:

- PLANNED + absent from all command states means publication has not occurred;
- PUBLISHED/CLAIMED/PROCESSED/UNKNOWN + missing command file is history ambiguity and converges to
  `MANUAL_REVIEW`, never republish.

## 7. OMS-owned mapper identity recovery

Self-review during I02 identified an additional restart issue in the I01 execution loop:

- a Host-owned PLANNED/PUBLISHED dispatch was registered in the mapper only in memory;
- restart before the command reached processed/unknown could lose the mapper join identity;
- once an OMS-owned command later reached processed/unknown, the old import path could reject it
  because the OMS intent already existed.

I02 fixes both:

1. `_restore_dispatch_plan_identities()` reconstructs mapper identity from the immutable
   Host-owned SUBMIT_LIMIT dispatch plan after restart.
2. `refresh_identities()` accepts an existing OMS intent only when an exact matching
   `qmt_execution_dispatches` row proves Host-owned dispatch authority.
3. `register_qmt_durable_submit(... allow_existing_order_from_dispatch=True)` only links the
   durable QMT identity; it does not create a second intent/order.

Tests cover restart from a PLANNED dispatch and later processed-command identity linking.

## 8. Failure-injection matrix

| Case | DB result | Spool result | Result |
|---|---|---|---|
| crash before submit atomic commit | RISK_ACCEPTED, no reservation/plan | none | PASS |
| crash after submit atomic commit | SUBMITTING + PLANNED | one deterministic recovery publish | PASS |
| orphan SUBMITTING/no dispatch | MANUAL_REVIEW | none | PASS |
| crash before cancel atomic commit | prior broker state preserved, no cancel reservation/plan | no cancel file | PASS |
| crash after cancel atomic commit | CANCEL_PENDING + PLANNED | one deterministic cancel publish | PASS |
| orphan CANCEL_PENDING/no dispatch | MANUAL_REVIEW, cancel resolved locally | no new file | PASS |
| expired submit PLANNED | MANUAL_REVIEW | zero publication | PASS |
| expired cancel PLANNED | MANUAL_REVIEW | zero publication | PASS |
| known exact spool frame | adopted | no duplicate publication | PASS |
| conflicting immutable frame | hard conflict/fail closed | no replacement | PASS |
| second leader | fenced by existing LeaderCoordinator | no second writer | PASS |
| risk reject | RISK_REJECTED | zero command | PASS |
| restart mapper identity | restored from immutable dispatch | no replay | PASS |
| processed OMS-owned command | linked to existing intent via exact dispatch authority | no duplicate order | PASS |

## 9. Formal verification

`formal/GuojinSimDispatchRecovery.tla` was extended to model:

- READY / RESERVED / ORPHAN / MANUAL_REVIEW order state;
- atomic reservation + dispatch-plan commit;
- legacy/fault-injected orphan sweep;
- PLANNED expiry;
- publication only when not expired;
- CLAIMED / PROCESSED / UNKNOWN;
- restart/history ambiguity.

Mandatory invariants now include:

```text
TypeOK
ReservationHasPlan
UnknownNeverBlindRepublishes
SideEffectAtMostOnce
ExpiredNeverPublished
NoInvisibleReservedRestart
```

GitHub CI step `TLC - Guojin simulation dispatch recovery`: **SUCCESS**.

All other permanent TLC models also passed.

## 10. Verification

GitHub Actions run `35598923724`, head
`56089e69a0a694332ad7d420b8f3f56874a776c4`:

```text
pytest -q                                      PASS — 451 passed
python tools/verify_workflow_contract.py       PASS
python tools/audit_side_effect_calls.py        PASS
python tools/build_qmt_deployments.py --check  PASS
python tools/verify_bridge_protocol_exhaustive.py PASS
python tools/verify_bridge_schema_contract.py  PASS
python tools/verify_broker_evidence_contract.py PASS
TLC - finite order state machine               PASS
TLC - submit/recovery protocol                 PASS
TLC - OMS leader lease                         PASS
TLC - broker evidence replay                   PASS
TLC - pre-submit restart recovery              PASS
TLC - risk precedence and fail-close           PASS
TLC - Bridge command protocol                  PASS
TLC - Guojin simulation dispatch recovery      PASS
TLC - Bridge event protocol                    PASS
TLC - broker evidence boundary                 PASS
TLC - Broker Evidence Contract v1              PASS
```

## 11. Safety declaration

```text
guojin_sim broker mutation during I02 = 0
production guojin mutation = 0
galaxy mutation = 0
generic mutation = 0
blind retry after UNKNOWN = 0
production LIVE_CANARY authority change = 0
```

No QMT instance, broker account or live command spool was used during I02.

## 12. Remaining runtime validation

The P6-T004 market-window runtime validation remains pending because I02 intentionally performs
crash-safety repair only.

The next runtime Gate should validate the now-repaired normal execution API:

```text
OrderIntent -> Risk -> atomic OMS dispatch -> guojin_sim -> BrokerEvidence -> OMS
```

using only `guojin_sim`.

## 13. Handoff

Implementation is ready for independent Architect review.
