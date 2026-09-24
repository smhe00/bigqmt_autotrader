---
workflow_schema: 1
phase: P6
task_id: P6-T014
iteration: I02
task_key: P6-T014-I02
reply_to: workflow/tasks/P6-T014-I02__archive-ready-anchor.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T014-I02__architect-review.md
---

# P6-T014-I02 Implementation Report

## 1. Result

- Status: `REVIEW_READY` / code repair PASS / runtime `BROKER_REJECTED`
- Implementation commit: 0e1471efec178a559cc064b84e513d886709d2f6
- Base commit: `f799830`
- Final commit: 0e1471efec178a559cc064b84e513d886709d2f6

## 2. Files changed

- `src/bigqmt_autotrader/qmt/instances.py`
- `tests/qmt/test_instance_discovery.py`
- `workflow/reports/P6-T014-I02__implementation-report.md`
- `workflow/control/WORKFLOW_STATE.yaml` (standard handoff only)

## 3. Implementation summary

Host instance discovery now considers both loose `bridge_ready` frames and
integrity-verified committed daily archives.  Archive evidence is accepted only
after checkpoint state, manifest hash, archive hash, filenames, trading day,
event count, stream digest, decoded protocol frames and account fingerprint all
agree.  The globally latest valid readiness frame still controls session
validation; corrupt, malformed, linked or mismatched archive evidence fails
closed.

Regression coverage proves archived-current-session recovery, newer loose
session precedence, corrupt archive rejection, malformed frame rejection and
manifest/archive mismatch rejection.

Runtime proof used the unchanged V05 session
`3578dff2dd104b15a04836a07a06e994`.  The repaired Host started without a V05
restart and drained 2,799 inbox files to zero while remaining healthy and
leader; stderr stayed empty.  A read-only snapshot command
`17976eefc78440889b2c99d900ccacb8` produced fresh exact `.SGT` tick evidence
at sequence 5,513 and `SNAPSHOT_EMITTED` at sequence 5,514.  SHENGANGTONG was
DETECTED with route fingerprint
`sha256:6c78368e541862400549d0b00a0c43b20e711196a1df303ef40d3dfd3d9cb217`.

The one authorized Core attempt used:

```text
client_order_id = p6t014-sgt-buy-01810-20260924
symbol          = 01810.SGT
side/quantity   = BUY 100
limit_price     = 27.00 (fresh exact tick 26.66)
rule_version    = guojin-sim-accept-all-v1
command_id      = simoms-efaf6d0a4f163a326382ed5b5a130271613d14589781c7a8
broker_token    = BQ43448f32606f93fb1790
frame_digest    = sha256:7d987d003c4883338bb56ad114a296731cad9eaa7b7cbece36a4fe116e81c027
broker_order_id = xt1098937191
```

QMT reported `SIMULATION_SUBMIT_CALL_RETURNED`; BrokerEvidence then converged
exactly once to `REJECTED`, filled quantity zero.  The broker rejection was
deterministic: error `120158`, `buy_unit=200`, `sell_unit=200`, while the task
required quantity <= 100.  No retry or cancel was sent.

## 4. Verification results

- Focused instance/archive suites: 34 passed in 2.03s.
- Full suite: 616 passed in 152.01s.
- Workflow contract: PASS.
- Core dependency boundary: PASS, 39 files scanned.
- Side-effect surface audit: PASS.
- Live repaired Host: backlog 2,799 -> 0, read model healthy, lease retained,
  quarantine 0, stderr 0 bytes.
- Durable lifecycle:
  `CREATED -> RISK_ACCEPTED -> SUBMITTING -> UNKNOWN -> RECONCILING -> REJECTED`.
  The temporary UNKNOWN is the designed post-publication reconciliation state,
  not unresolved ambiguity; final unresolved UNKNOWN/MANUAL_REVIEW count is 0.

## 5. Safety declaration

No prohibited side effect occurred:

```text
guojin_sim submits = 1 / 1
guojin_sim cancels = 0 / 1
read-only snapshot commands = 1
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
blind retries = 0
fills = 0
```

## 6. Deviations / unresolved items

The archive-readiness code objective and real backlog replay gate passed.  The
SGT fill objective did not pass because `01810.SGT` requires a 200-share board
lot, incompatible with this iteration's 100-share ceiling.  A next iteration
must add an explicit instrument trading-unit preflight and may use a different
fresh exact `.SGT` candidate whose buy unit is 100.  The consumed submit must
not be retried within I02.

## 7. Handoff to Architect

After filling this report, run:

python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>

Then run:

python tools/verify_workflow_contract.py

Commit the report and WORKFLOW_STATE changes together. Do not modify the Architect review
and do not create the next task.
