# Order State Machine

Date: 2026-09-12

Status: **normative through P1**

## States and applied transitions

```text
CREATED
  -> RISK_REJECTED
  -> RISK_ACCEPTED
  -> ABORTED

RISK_ACCEPTED
  -> SUBMITTING
  -> ABORTED

SUBMITTING
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

`ABORTED` is the fail-safe terminal state for a durable pre-side-effect orphan discovered after restart. Only `CREATED` and `RISK_ACCEPTED` may enter it. An aborted intent is never resumed or submitted automatically; a strategy must generate a new durable identity and pass risk again.

## Terminal states

- `RISK_REJECTED`
- `ABORTED`
- `FILLED`
- `CANCELLED`
- `REJECTED`
- `MANUAL_REVIEW`

`MANUAL_REVIEW` is terminal to automation, not necessarily to a future audited human-resolution workflow. No implicit mutation out of it is permitted.

## Safety invariants

1. `SUBMITTING + submit_call_started=1` is durably committed before any submit side effect.
2. `CANCEL_PENDING + cancel_call_started=1` is durably committed before any cancel side effect.
3. One durable client-order identity produces at most one simulated submit call.
4. One durable cancel reservation produces at most one simulated cancel call.
5. `UNKNOWN` may only leave through `RECONCILING`.
6. `UNKNOWN` never triggers automatic submit or cancel retry.
7. A pre-side-effect orphan after restart becomes `ABORTED`, never an automatic submit opportunity.
8. Duplicate evidence is idempotent; recognized stale evidence cannot downgrade aggregate state.
9. Broker-order identity is immutable once learned.
10. Filled quantity is monotonic, bounded by original quantity, and reconciled with broker lifecycle status.
11. Terminal states do not downgrade.
12. Illegal or contradictory transitions/facts fail closed.
13. Every OMS durable write is leader-fenced inside the SQLite write transaction.

## Broker-fact normalization

Callback ingestion and active reconciliation use the same broker-fact merge rules:

- `ACKNOWLEDGED + known positive fill` normalizes to `PARTIALLY_FILLED`;
- a full known fill normalizes ACK/partial evidence to `FILLED`;
- `FILLED` requires filled quantity equal to order quantity;
- `REJECTED` cannot coexist with a positive fill;
- a late lower filled quantity cannot reduce the aggregate;
- a different broker order ID for the same durable identity is a conflict.

Raw observations remain auditable even when their aggregate effect is duplicate or stale.

## Ambiguity blocking

`SUBMITTING`, `UNKNOWN`, `RECONCILING`, and `MANUAL_REVIEW` block potentially duplicative new exposure until the explicit recovery policy resolves them. `ABORTED` is terminal and carries no execution authority.

## Event ordering

The state machine is monotonic, not timestamp-trusting. A late event cannot override a stronger aggregate fact merely because its timestamp appears newer or older. Ordering safety is based on the state relation, broker identity, filled-quantity monotonicity, evidence identity, and durable recovery markers.

## Verification

The current FSM contains **14 states** and **25 applied edges**. CI independently classifies all **196 / 196** `(current_status, requested_status)` pairs and TLC exhaustively model-checks the finite `OrderFSM` abstraction. See `docs/FORMAL_VERIFICATION.md` and `docs/P1_GATE_RESULT_20260912.md`.
