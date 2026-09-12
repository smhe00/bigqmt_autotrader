# P1 Implementation Report

Date: 2026-09-12

Phase: **P1 — Crash-Recoverable Offline OMS**

Status: **IN PROGRESS — NOT YET GATE PASS**

Safety boundary: simulated driver only. No Big QMT import, credential, live submit, or live cancel path exists.

## Implemented

### Durable OMS core

- SQLite WAL, foreign keys, `synchronous=FULL`.
- Forward-only packaged migrations; current schema version: **v4**.
- Fail-close on a database schema newer than the running binary.
- Durable `order_intents`, `broker_orders`, `risk_decisions`, `order_events`, `runtime_sessions`.
- Database-enforced `(account_fingerprint, client_order_id)` uniqueness.
- Persistent monotonic state transitions with immutable audit evidence.
- Startup session rejects new intents until reconciliation completes.

### Submit safety

- `SUBMITTING + submit_call_started=1` is committed before the simulated broker side effect.
- One durable client-order identity can invoke simulated submit at most once.
- Lost/timeout response enters `UNKNOWN`; it is never blindly resubmitted.
- Restart recovery forces `UNKNOWN -> RECONCILING` and queries broker evidence.
- No broker evidence after an ambiguous reservation converges to `MANUAL_REVIEW` rather than resubmit.

### Cancel safety

- `CANCEL_PENDING + cancel_call_started=1 + cancel_outcome_resolved=0` is committed before the simulated cancel side effect.
- One durable order can invoke simulated cancel at most once.
- Cancel response loss enters `UNKNOWN`; it is never blindly recancelled.
- `cancel_outcome_resolved` is persisted independently from aggregate order status, so a partial-fill callback cannot erase an unresolved cancel attempt.
- Restart reconciliation resolves accepted, rejected/not-accepted and crash-before-side-effect cancel cases without a second cancel call.

### Single-writer ownership

- SQLite-backed OMS leader lease with `session_id + lease_token + fencing epoch`.
- A second OMS fails closed while the current lease is live.
- Expired takeover increments the fencing epoch.
- A fenced/expired old leader cannot heartbeat, submit, cancel, reconcile or persist post-broker ACK state.
- Submit/cancel paths re-check the fencing token after durable reservation, immediately before the broker side effect, and again before persisting the result.
- If takeover occurs during a broker call, the old writer is fenced and the successor must reconcile the durable ambiguous state.

### Broker evidence / replay

- Durable `broker_evidence_keys` and `broker_evidence_observations` journal.
- Every raw observation is retained for audit.
- A logical evidence fingerprint can affect the aggregate state at most once.
- Exact replay is recorded but does not repeat a state transition.
- Reused source-event IDs with changed facts fail closed.
- Broker-order identity mismatch fails closed.
- Filled quantity is globally monotonic and bounded by original order quantity.
- Stale ACK/order evidence cannot erase a known partial fill.
- Contradictory `FILLED`/quantity and `REJECTED`/positive-fill evidence fail closed.

### Failure injection

Verified SQLite failure boundaries include:

- database becomes query-only before intent persistence -> zero broker calls;
- `SUBMIT_RESERVED` transaction fails -> rollback to pre-side-effect state, zero broker calls;
- broker accepts submit but `SUBMIT_ACK` persistence fails -> durable `SUBMITTING`, restart reconcile, no resubmit;
- broker accepts cancel but `CANCEL_ACK` persistence fails -> durable unresolved cancel, restart reconcile, no recancel.

## Verification

Latest verified implementation commit: `468574db888cd3eb7dc4f15bfa082b4e93869f1f`

GitHub Actions:

- CPython 3.11: **57 passed**.
- CPython 3.12: **57 passed**.
- exhaustive Python/formal state-request conformance: **169 / 169 PASS**.
- TLC `OrderFSM`: **PASS**.
- TLC `SubmitProtocol`: **PASS**.
- TLC `LeaderLease`: **PASS**.
- TLC `EvidenceReplay`: **PASS**.

The formal CI gate is mandatory. Safety-critical model changes must pass TLC before the phase can advance.

## Formal verification boundary

The finite abstractions currently prove/check properties including:

- terminal absorption and monotonic order-state behavior;
- `UNKNOWN` can only leave via `RECONCILING`;
- no path from ambiguous post-submit state back to a new submit opportunity;
- durable reservation before submit/cancel side effect;
- at-most-one submit and at-most-one cancel in the modeled protocol;
- leader mutual exclusion and fencing;
- expired/fenced writers cannot regain execution authority;
- broker evidence fingerprint applied at most once;
- replay/out-of-order evidence cannot regress aggregate execution facts.

This is not a proof of CPython, SQLite, Windows, QMT, networking or broker infrastructure. Those boundaries are addressed with transaction tests, fault injection, replay tests and later QMT integration tests.

See `docs/FORMAL_VERIFICATION.md` and `docs/FORMAL_VERIFICATION_RESULT_20260912.md` for the formal-verification policy and original state-machine evidence.

## Safety audit

The project still contains no real Big QMT execution integration:

- no `xtquant` execution path;
- no `passorder` path;
- no live credentials;
- no real submit/cancel capability.

`qmt_side/BIGQMT_EXECUTION_BRIDGE.py` remains fail-closed.

## Why P1 is still not PASS

Most original P1 infrastructure gaps are now closed. Remaining Gate work is narrower:

1. define and verify deterministic recovery policy for crashes/failures in **pre-side-effect** states such as durable `CREATED` or `RISK_ACCEPTED`, so an order cannot remain silently stranded and cannot be ambiguously reissued;
2. complete the systematic crash-boundary matrix around intent/risk/reservation/evidence persistence, including the chosen pre-side-effect recovery policy;
3. ensure callback/evidence ingestion is invoked only through the fenced OMS writer once the callback service layer is connected;
4. run an end-to-end invariant audit over every submit/cancel call site proving no durable order identity can reach a second broker side-effect call;
5. produce the final P1 Gate report and rerun all tests/formal models from one immutable commit.

P2 must not begin until these items are closed and P1 is explicitly marked PASS.

## Next implementation slice

Next work remains P1-only:

- resolve pre-side-effect orphan semantics;
- add corresponding state-machine/formal-model rules;
- expand crash-injection coverage for those rules;
- complete the no-double-side-effect audit;
- issue the P1 Gate decision.
