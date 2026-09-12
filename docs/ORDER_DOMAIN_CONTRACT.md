# Order Domain Contract (P0)

Status: **normative for P0/G0**

## 1. Safety objective

The platform prefers a missed execution over an accidental duplicate exposure. A submit timeout is therefore **not** permission to submit again. It creates an `UNKNOWN` order that must be reconciled.

## 2. OrderIntent

A strategy may create an `OrderIntent`; it may not call QMT or a broker driver directly.

Required fields:

- `client_order_id`: permanent account-scoped idempotency key.
- `strategy_id` and `strategy_version`: executable provenance.
- `account_fingerprint`: non-secret deployment identity of the account.
- `symbol`, `side`, `quantity`, `order_type`, `limit_price`.
- `created_at`, `expires_at`: timezone-aware timestamps.
- `signal_id`, `reason_code`: decision provenance.

P0 permits only `order_type=LIMIT`.

### Numeric rule

Prices and monetary risk thresholds must use `Decimal` or integer smallest units. Binary floating point is forbidden for risk threshold comparison.

### Time rule

An intent at or after `expires_at` is expired and must never be submitted.

## 3. Idempotency

`(account_fingerprint, client_order_id)` is permanently unique.

P0 contains an in-memory executable semantic test. P1 MUST make the database authoritative with:

```sql
UNIQUE(account_fingerprint, client_order_id)
```

A duplicate key never causes a second broker submit.

## 4. Submit contract

Before any future live submit implementation may call QMT:

1. intent exists durably;
2. risk decision exists durably;
3. order is durably marked `SUBMITTING`;
4. the transaction is committed;
5. only then may one broker submit call occur.

If the response is lost, delayed or ambiguous, the order becomes `UNKNOWN`. **Automatic resubmit is forbidden.**

## 5. Broker identifiers

The domain keeps these concepts separate:

- `client_order_id`: our idempotency key;
- QMT/local order identifier;
- broker/exchange order or contract identifier.

Driver code may map version-specific QMT fields, but it may not collapse these identities into one field.

## 6. Evidence and audit

P1 must persist the raw evidence that caused each transition. Duplicate, stale and out-of-order events may be ignored for aggregate state changes, but they must remain auditable.

## 7. External/manual orders

Orders not created by our OMS are `EXTERNAL`. They affect positions and risk but must never be rewritten to look like strategy orders.
