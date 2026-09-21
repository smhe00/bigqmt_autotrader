---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I01
task_key: P6-T004-I01
reply_to: workflow/tasks/P6-T004-I01__guojin-sim-single-writer-execution-loop.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T004-I01__architect-review.md
---

# P6-T004-I01 Implementation Report

## 1. Result
- Status: `REVIEW_READY`
- Implementation commit: eb27867af04160b3ccbc97d91e6405491e2be2ab
- Final commit: eb27867af04160b3ccbc97d91e6405491e2be2ab
`GuojinSimOmsRuntime` continues to own the single `host_oms.sqlite3` connection,
`LeaderCoordinator` lease and repository write guard.  The new public
`execute_intent()` / `cancel_intent()` methods run under that same lease and do
not instantiate `OfflineOms` or another leader.  Every dispatch-plan insert,
state update, risk persistence and lifecycle mutation is inside the guarded
repository transaction boundary.

## 3. Risk -> dispatch path
The typed public API is `GuojinSimOmsRuntime.execute_intent(intent, snapshot,
policy)`.  It evaluates deterministic risk internally, then persists the
intent and decision. A rejected decision produces `RISK_REJECTED` and no QMT
command. An accepted intent derives an immutable command ID from account,
current QMT session and client order ID; broker token remains the established
account/client hash; the exact encoded frame SHA-256 is persisted before spool
publication.

## 4. Durable dispatch / crash-window matrix

| Boundary | Recovery rule | Duplicate broker mutation possible? | Test |
|---|---|---|---|
| before dispatch-plan commit | no order side effect exists | No | regression suite |
| after plan / before spool publish | exact absence in all active spool states permits deterministic publish | No | `test_planned_dispatch_recovers_only_when_exact_absence_is_provable` |
| after spool publish / before local mark | exact immutable file is discovered and adopted | No | deterministic repeat test |
| inbox | retain/reconcile exact frame | No | command spool idempotency gate |
| claimed | observe only; never reissue | No | recovery implementation + protocol gate |
| processed | observe only; lifecycle awaits BrokerEvidence | No | command-result/evidence regressions |
| unknown | mark UNKNOWN; no automatic retry | No | bridge protocol exhaustive gate |
| conflicting frame | durable identity conflict, fail closed | No | command spool conflict gate |
| archive/history ambiguity | `MANUAL_REVIEW`; no guess/publish | No | `GuojinSimDispatchRecovery.tla` in CI |

## 5. Submit/cancel idempotency
Submit IDs are deterministic for pinned account + QMT session + client order ID;
cancel IDs additionally bind the trusted persistent broker order ID. Repeating
the same submit recovers/adopts the same immutable frame. Repeating a cancel
returns the existing command without publishing another broker mutation. A
terminal order returns a no-op.

## 6. Command-result / BrokerEvidence boundary
Simulation `command_result` is now durably recorded as control-plane evidence.
It can begin/continue reconciliation but cannot produce ACKNOWLEDGED,
CANCELLED or FILLED. Only the already calibrated ORDER/DEAL/active-query mapper
feeds `EvidenceJournal` and advances lifecycle state.

## 7. Restart / session rollover
Startup recovers only dispatch plans for the manifest-pinned current session.
Known inbox/claimed/processed/unknown frames are adopted without republish;
missing-after-published state fails closed to `MANUAL_REVIEW`. Existing P6-T003
session rollover guard remains unchanged: an old Host does not process/publish
for a new QMT session.

## 8. Runtime validation
PENDING MARKET WINDOW. No QMT instance, spool or broker endpoint was accessed
while implementing this task.

## 9. Mutation accounting
```text
guojin_sim submits = 0
guojin_sim cancels = 0
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
UNKNOWN blind retries = 0
```

## 10. Verification
```text
python tools/verify_workflow_contract.py:
pytest -q: PASS (440 passed)
python tools/audit_side_effect_calls.py: PASS
python tools/build_qmt_deployments.py --check: PASS
python tools/verify_bridge_protocol_exhaustive.py: PASS (4608 transitions)
python tools/verify_bridge_schema_contract.py: PASS
python tools/verify_broker_evidence_contract.py: PASS (7200 cases)
formal/TLC: PENDING LOCAL JAVA; all existing and new TLC jobs are required by CI
```

## 11. Safety declaration
Confirmed: the execution API is enabled only for the manifest-pinned
`guojin_sim` `SIMULATION_CALIBRATION` instance with explicit Host mutation
authorization, expected build/fingerprint/session and held leader lease.
Production Guojin, Galaxy and generic mutation counts are zero.

## 12. Deviations / blockers
Local TLC could not run because Java is not installed on this workstation. The
new dispatch-recovery model is committed to the mandatory GitHub CI TLC matrix.

## 13. Handoff
Use `tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>`, verify the workflow
contract, and commit/push report + state. Do not edit Architect review or create the next task.
