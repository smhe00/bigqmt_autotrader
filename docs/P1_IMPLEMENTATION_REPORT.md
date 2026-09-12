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
- mandatory TLA+/TLC formal-verification gate for order lifecycle and submit/recovery protocol.
- exhaustive implementation/formal-contract conformance checking for all 169 state/request pairs.

## Verification

Latest formal candidate commit: `3c9270cb4244441d8f4e8e2093ba55a4be3df2fc`

GitHub Actions:

- CPython 3.11: **28 passed**.
- CPython 3.12: **28 passed**.
- exhaustive state/request conformance: **169 / 169 PASS**.
- TLC `OrderFSM`: **PASS**, 124 generated / 13 distinct reachable states, queue exhausted.
- TLC `SubmitProtocol`: **PASS**, 149 generated / 51 distinct reachable states, queue exhausted.
- TLC temporal properties: **2 branches checked, PASS**.

See `docs/FORMAL_VERIFICATION.md` for the permanent gate definition and `docs/FORMAL_VERIFICATION_RESULT_20260912.md` for exact evidence and scope.

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

## Formal state-machine gate

State-machine formal verification is now **PASS** for the current abstraction and is a permanent required CI gate.

Verified safety properties include terminal absorption, total/exclusive event classification, UNKNOWN-only-via-RECONCILING recovery, no path from ambiguity back to pre-submit states, durable-reservation-before-side-effect, broker-order causality, and at-most-one submit.

Verified liveness properties are conditional on the explicit strong-fairness assumptions in the TLA+ model: restart and continuously/repeatedly enabled reconciliation actions eventually execute.

This is an exhaustive proof over the finite abstract models and a complete 169-pair conformance check of the Python transition function. It is not a proof of SQLite, CPython, Windows, QMT, networking, or the broker infrastructure.

## Safety audit

Repository code search at this milestone found:

- no `xtquant` occurrence;
- no `passorder` occurrence.

`qmt_side/BIGQMT_EXECUTION_BRIDGE.py` still advertises no live submit/cancel capability and throws `E_TRADING_DISABLED` for both entry points.

## Why P1 is not PASS yet

The core state machine and submit/recovery abstraction now have a formal PASS, but the original P1 exit criterion is broader. Remaining work:

1. implement offline simulated cancellation execution and its ambiguity/recovery path;
2. systematic crash injection around all listed transaction boundaries, not only the submit reservation boundary;
3. explicit two-writer/single-leader contention test and policy;
4. migration runner/version checks instead of `SCHEMA_V1` being only in Python;
5. event fingerprint/dedup contract for replayed callbacks;
6. replay-based reconciliation cases for duplicate/out-of-order trade/order evidence;
7. database failure tests (read-only, disk/full-like write failure where practical);
8. extend the formal protocol model as those P1 mechanisms are implemented, especially cancel at-most-once, leader ownership and callback deduplication.

## Next implementation slice

Next work should remain P1-only and focus on:

- simulated cancel state machine/execution;
- crash-point/failure injector abstraction;
- leader ownership guard;
- packaged forward-only migration runner;
- expanded replay/fault test matrix;
- matching formal-model extensions for every new safety-critical mechanism.

P2 risk-engine implementation must not begin until those P1 recovery guarantees are reviewed.
