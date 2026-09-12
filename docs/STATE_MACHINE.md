# Order State Machine (P0)

Status: **normative for P0/G0**

## States

```text
CREATED
  -> RISK_REJECTED
  -> RISK_ACCEPTED
       -> SUBMITTING
            -> ACKNOWLEDGED
            -> REJECTED
            -> UNKNOWN

ACKNOWLEDGED
  -> PARTIALLY_FILLED
  -> FILLED
  -> CANCEL_PENDING

PARTIALLY_FILLED
  -> FILLED
  -> CANCEL_PENDING
  -> CANCELLED

CANCEL_PENDING
  -> CANCELLED
  -> PARTIALLY_FILLED
  -> FILLED
  -> UNKNOWN

UNKNOWN
  -> RECONCILING
       -> ACKNOWLEDGED
       -> PARTIALLY_FILLED
       -> FILLED
       -> REJECTED
       -> CANCELLED
       -> MANUAL_REVIEW
```

The `PARTIALLY_FILLED -> CANCELLED` edge is intentionally present so a cancel/fill callback race can converge while filled quantity remains recorded separately.

## Invariants

1. `SUBMITTING` must have been committed before a broker call.
2. `UNKNOWN` may only leave through `RECONCILING`.
3. `UNKNOWN` never triggers automatic submit retry.
4. Duplicate events are idempotent no-ops.
5. Recognized stale events are audit evidence but cannot downgrade aggregate state.
6. Terminal states do not downgrade.
7. Illegal transitions fail closed.

Terminal states in P0 are:

- `RISK_REJECTED`
- `FILLED`
- `CANCELLED`
- `REJECTED`
- `MANUAL_REVIEW`

`MANUAL_REVIEW` is terminal to automation, not necessarily to human operations. A later phase may add an explicit audited operator resolution command; it must not be an implicit state mutation.

## Ambiguity blocking

`SUBMITTING`, `UNKNOWN`, `RECONCILING`, and `MANUAL_REVIEW` are ambiguity states. They block potentially duplicative new exposure until resolved by an explicit policy.

## Event ordering

The state machine is monotonic, not timestamp-trusting. A late event cannot override a more advanced aggregate merely because its timestamp is newer or older. P1 must retain event timestamps and raw payloads for reconciliation and audit.
