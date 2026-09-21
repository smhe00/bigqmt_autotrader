---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I02
task_key: P6-T004-I02
reply_to: workflow/tasks/P6-T004-I02__close-pre-dispatch-crash-windows.md
status: AWAITING_AGENT
owner: agent
review_target: workflow/reviews/P6-T004-I02__architect-review.md
---

# P6-T004-I02 Implementation Report

## 1. Result
- Status: `AWAITING_AGENT`
- Implementation commit:
- Base commit:
- Final commit:

## 2. Atomic submit boundary
Agent: describe transaction and prove reservation/plan atomicity.

## 3. Atomic cancel boundary
Agent: describe transaction and prove reservation/plan atomicity.

## 4. Startup invariant sweep
Agent: describe handling of reservation-without-dispatch and identity conflicts.

## 5. Expired plan handling
Agent: prove zero spool publication and safe durable convergence.

## 6. Absence/history contract
Agent: explain why absence is provable, including retention/archive behavior.

## 7. Failure-injection matrix
| Case | DB result | Spool result | PASS/FAIL |
|---|---|---|---|
| crash before submit commit | | | PENDING |
| crash after submit commit | | | PENDING |
| orphan SUBMITTING/no dispatch | | | PENDING |
| crash before cancel commit | | | PENDING |
| crash after cancel commit | | | PENDING |
| orphan CANCEL_PENDING/no dispatch | | | PENDING |
| expired submit plan | | | PENDING |
| expired cancel plan | | | PENDING |
| known exact spool frame | | | PENDING |
| conflicting frame | | | PENDING |
| second leader | | | PENDING |
| risk reject | | | PENDING |

## 8. Formal verification
Agent: list updated model/invariants and TLC result.

## 9. Verification
```text
workflow contract =
pytest =
side-effect audit =
deployment generator check =
bridge protocol =
schema contract =
broker evidence contract =
TLC =
```

## 10. Safety declaration
```text
guojin_sim broker mutation during I02 = 0
production guojin mutation = 0
galaxy mutation = 0
generic mutation = 0
blind retry after UNKNOWN = 0
```

## 11. Remaining runtime validation
Agent: state whether P6-T004 runtime market-window validation remains pending.

## 12. Handoff
Use `tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>`, verify contract, commit
and push report + state.
