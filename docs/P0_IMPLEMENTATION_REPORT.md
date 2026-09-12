# P0 Implementation Report

Date: 2026-09-12

Gate: **G0 — Order Safety Contract Frozen**

Decision: **PASS for entry into P1 offline OMS development**.

This PASS does **not** authorize live QMT trading, order submission, cancellation, account credential use, or live-mode unlock.

## Delivered

- Project/package skeleton and CI.
- Normative `OrderIntent`, `Order`, `Trade`, `RiskDecision` domain models.
- Decimal-only price contract and timezone-aware intent expiry.
- Account-scoped `client_order_id` uniqueness semantics.
- Deterministic monotonic order state machine.
- Duplicate/stale event no-downgrade behavior.
- Explicit `UNKNOWN -> RECONCILING` recovery gate.
- Ambiguity exposure blocker for `SUBMITTING/UNKNOWN/RECONCILING/MANUAL_REVIEW`.
- Stable risk reason-code and system error-code enums.
- Python-3.6-syntax-compatible QMT-side bridge skeleton.
- QMT-side submit/cancel entry points that always fail with `E_TRADING_DISABLED`.
- Failure matrix and authority/security boundary.

## Verification

GitHub Actions workflow: `ci`.

Verified on:

- CPython 3.11: **19 passed**.
- CPython 3.12: **19 passed**.

Tests cover:

- Decimal vs binary-float price semantics.
- timezone-aware expiry.
- account-scoped idempotency key behavior.
- legal/illegal state transitions.
- duplicate event idempotence.
- late callback no-downgrade.
- terminal-state no-downgrade.
- submit timeout UNKNOWN discipline.
- cancel/fill race convergence.
- UNKNOWN exposure blocking.
- stable error/reason codes.
- bridge Python 3.6 syntax contract.
- bridge advertised capabilities.
- live submit/cancel fail-closed behavior.

## G0 invariants frozen

1. No broker call before durable `SUBMITTING` state in future P1/P4 implementation.
2. Submit uncertainty becomes `UNKNOWN`; automatic resubmit is forbidden.
3. `UNKNOWN` can only transition through `RECONCILING`.
4. Aggregate order state is monotonic under duplicate, late and stale evidence.
5. `(account_fingerprint, client_order_id)` is the permanent idempotency identity.
6. Strategies do not receive QMT authority.
7. The P0 QMT bridge cannot trade.

## Known limitations intentionally deferred

- P0 registry is process-local; P1 must enforce the idempotency key with SQLite UNIQUE constraint.
- Raw event evidence is not persistent yet.
- Crash consistency is not implemented yet.
- No simulated execution driver yet.
- No startup reconciliation implementation yet.
- Four-level risk rules are contract-only until P2.
- No Big QMT import/query/callback code exists yet; read-only integration begins in P3.

## P1 entry conditions

P1 may add only offline/persistent infrastructure:

- SQLite WAL schema/migrations.
- single-writer repository/service boundary.
- simulated execution driver.
- persistent order events/risk decisions.
- startup recovery/reconciliation against the simulated driver.
- crash-boundary/failure-injection tests.

P1 must not weaken `qmt_side/BIGQMT_EXECUTION_BRIDGE.py` fail-closed behavior and must not add a real broker submit/cancel implementation.
