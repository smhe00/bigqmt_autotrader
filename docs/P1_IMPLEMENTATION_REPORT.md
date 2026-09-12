# P1 Implementation Report

Date: 2026-09-12

Phase: **P1 — Crash-Recoverable Offline OMS**

Status: **IN PROGRESS — NOT YET GATE PASS**

Safety boundary: simulated driver only. No Big QMT import, credential, live submit, or live cancel path exists.

## Implemented in first P1 slice

- SQLite database with WAL mode, foreign keys and `synchronous=FULL`.
- Durable `order_intents`, `broker_orders`, `risk_decisions`, `order_events`, `runtime_sessions`.
- database-enforced `(account_fingerprint, client_order_id)` primary-key uniqueness.
- persistent monotonic state transitions with immutable event evidence.
- startup session begins non-reconciled and rejects new intents until `recover()` succeeds.
- `prepare_submit()` commits `SUBMITTING + submit_call_started=1` before any simulated side effect.
- deterministic simulated broker driver with before-accept and after-accept response-loss injection.
- submit exceptions after the side-effect boundary are normalized to `UNKNOWN`.
- restart recovery converts abandoned `SUBMITTING` to `UNKNOWN`, then `RECONCILING`.
- broker evidence can converge to the known broker state without a second submit.
- absence of broker evidence converges to `MANUAL_REVIEW`, preserving the no-resubmit safety policy.
- order state survives database close/reopen.

## Verification

Verified commit: `4293376af880f082bf86be21ffa895f241416d3d`

GitHub Actions:

- CPython 3.11: **28 passed**.
- CPython 3.12: **28 passed**.

P1-specific tests currently include:

- WAL mode assertion;
- startup reconciliation gate;
- normal durable submit reservation;
- database duplicate-key idempotency;
- timeout after simulated broker accept -> UNKNOWN -> restart reconcile -> ACKNOWLEDGED, submit count stays 1;
- timeout before accept -> UNKNOWN -> restart -> MANUAL_REVIEW, submit count stays 1;
- simulated crash after durable submit reservation but before side effect -> restart -> MANUAL_REVIEW, submit count stays 0;
- persistent event evidence across reconciliation;
- durable order state after SQLite reopen.

## Safety audit

Repository code search at this milestone found:

- no `xtquant` occurrence;
- no `passorder` occurrence.

`qmt_side/BIGQMT_EXECUTION_BRIDGE.py` still advertises no live submit/cancel capability and throws `E_TRADING_DISABLED` for both entry points.

## Why P1 is not PASS yet

The first slice proves the central submit-ambiguity invariant, but the original P1 exit criterion is broader. Remaining work:

1. implement offline simulated cancellation and its ambiguity/recovery path;
2. systematic crash injection around all listed transaction boundaries, not only the submit reservation boundary;
3. explicit two-writer/single-leader contention test and policy;
4. migration runner/version checks instead of `SCHEMA_V1` being only in Python;
5. event fingerprint/dedup contract for replayed callbacks;
6. replay-based reconciliation cases for duplicate/out-of-order trade/order evidence;
7. database failure tests (read-only, disk/full-like write failure where practical);
8. P1 end-to-end invariant audit proving no code path can call the simulated submit twice for one durable order identity.

## Next implementation slice

Next work should remain P1-only and focus on:

- simulated cancel state machine;
- crash-point/failure injector abstraction;
- leader ownership guard;
- packaged forward-only migration runner;
- expanded replay/fault test matrix.

P2 risk-engine implementation must not begin until those P1 recovery guarantees are reviewed.
