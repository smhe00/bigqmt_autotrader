# P1 Offline OMS Scope

Goal: prove persistence, idempotency, recovery and reconciliation **without connecting to QMT**.

## Required implementation

1. SQLite database opened in WAL mode.
2. Forward-only migration bootstrap.
3. Tables for order intents, broker orders, order events, risk decisions and runtime sessions.
4. Database `UNIQUE(account_fingerprint, client_order_id)` constraint.
5. Single-writer OMS repository/service.
6. Deterministic simulated driver with submit/query/cancel evidence; no real network/broker dependency.
7. Pre-submit transaction boundary: intent/risk/order state must be committed before simulated side effect.
8. Submit uncertainty path to `UNKNOWN` with no automatic resubmit.
9. Startup recovery that marks the runtime non-trading, loads incomplete orders and reconciles before accepting new exposure.
10. Crash/failure tests around persistence and simulated side-effect boundaries.

## Explicit non-goals

- Big QMT imports.
- account credentials.
- live broker calls.
- live runtime mode.
- production strategy scheduling.
- Web console.

## P1 exit gate

Every forced-crash boundary must restart into an explainable state, and no failure path may produce a second simulated broker submit for the same durable client order identity.
