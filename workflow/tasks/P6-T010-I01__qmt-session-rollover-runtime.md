---
workflow_schema: 1
phase: P6
task_id: P6-T010
iteration: I01
task_key: P6-T010-I01
state: PLANNED
owner: architect
audit_base_commit: d3fb18ed45f4ff2ac0b68db396301999288bb0b1
expected_report: workflow/reports/P6-T010-I01__implementation-report.md
expected_review: workflow/reviews/P6-T010-I01__architect-review.md
---

# P6-T010-I01 — QMT Session-Rollover Recovery Runtime Gate

## Objective

Validate QMT-side session rollover/restart recovery with one resting A-share simulation order:

> a broker-ACKed passive order survives QMT model/bridge restart without duplicate submit, Host fails closed across the session change, and after the required Host recovery/restart the same broker order is reconciled and cancelled exactly once.

## Scenario

1. normal OMS passive LIMIT order on a liquid A-share/ETF;
2. reach broker-evidence-backed ACKNOWLEDGED;
3. record client_order_id, token, broker_order_id, dispatch count and old QMT session;
4. restart/reload the guojin_sim QMT model/bridge so a new bridge session is created;
5. observe the designed Host session-rollover guard; no automatic submit replay is allowed;
6. perform only the required safe Host restart/recovery if the guard requires it;
7. reconcile the same active broker order from query/callback evidence;
8. prove total broker submit count remains one;
9. issue one exact OMS-owned cancel and converge to CANCELLED.

## Pass criteria

- QMT session ID changes and is detected;
- no silent continuation on stale session;
- no duplicate SUBMIT_LIMIT publication or broker submit;
- same client/token/broker_order_id recovered;
- one exact cleanup cancel;
- final CANCELLED, no UNKNOWN/MANUAL_REVIEW left unresolved;
- production/Galaxy/generic mutation = 0.

## Mutation budget

guojin_sim submit <= 1
guojin_sim cancel <= 1
production mutation = 0

## Scope lock

Do not change product code during the runtime campaign. If rollover exposes a defect, preserve artifacts and return REVIEW_READY/blocked evidence for a separate fix iteration.
