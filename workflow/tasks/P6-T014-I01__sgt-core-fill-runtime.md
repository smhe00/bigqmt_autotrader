---
workflow_schema: 1
phase: P6
task_id: P6-T014
iteration: I01
task_key: P6-T014-I01
state: AGENT_READY
owner: agent
audit_base_commit: 7401242306ecc28db683164c587c0081f88dda0a
expected_report: workflow/reports/P6-T014-I01__implementation-report.md
expected_review: workflow/reviews/P6-T014-I01__architect-review.md
---

# SGT Core Linked-Route Fill Runtime Gate

## Objective

Validate during the current market window:

> one typed `.SGT` `OrderIntent` submitted through the post-P7
> `GuojinSimOmsRuntime.execute_intent(intent)` Core path traverses the detected
> SHENGANGTONG linked route and converges exactly once to BrokerEvidence-backed
> `FILLED`.

This is runtime validation only. Do not modify product code in this task.

## Scope

Runtime target is exclusively:

```text
instance_id = guojin_sim
execution_mode = SIMULATION_CALIBRATION
simulation_only = true
bridge_build = p5-simulation-calibration-8
pinned OMS account type = STOCK
```

Use the current Core API without `RiskSnapshot` or `RiskPolicy`:

```text
OrderIntent -> GuojinSimOmsRuntime.execute_intent(intent)
```

Use one calibrated five-digit `.SGT` symbol, quantity <= 100, and a fresh
exact-symbol quote. Prefer a marketable LIMIT BUY when the current quote and
simulation balance make that safe. Do not manufacture positions.

Before mutation:

1. confirm current `main`, workflow contract and exact manifest/session/build;
2. start the repaired Host and confirm backlog replay completes without leader
   lease loss;
3. confirm no unresolved `UNKNOWN` or `MANUAL_REVIEW`;
4. request/read a fresh exact-symbol `.SGT` tick;
5. confirm SHENGANGTONG is DETECTED and capture its route fingerprint;
6. stop Host and respect the lease boundary before the one Core submit;
7. restart Host to ingest ORDER/DEAL/query evidence and reconcile to terminal.

Record exact client ID, accepted execution authorization and rule version,
command ID, frame digest, broker token, broker order/trade IDs, raw status,
route metadata, lifecycle, fill quantity and duplicate evidence behavior.

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T014-I01__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T014-I01__architect-review.md

## Safety boundaries

- `guojin_sim` submit <= 1.
- `guojin_sim` cancel <= 1, cleanup only.
- Production Guojin/Galaxy/generic mutation = 0.
- No blind retry after any ambiguous broker crossing.
- A control-plane command result is not broker ACK/fill evidence.
- Pinned STOCK OMS identity remains authority; linked route evidence may report
  `route_account_type=SHENGANGTONG` and its separate fingerprint.
- BrokerEvidence is the only lifecycle authority.
- Stop on session/build/account/tick/route ambiguity or any UNKNOWN.
- Do not change Core, OMS, Risk, mapper, bridge or production authority.

## Required verification

- Prove exactly one submit identity crossed the simulator boundary.
- Prove cumulative fill equals original quantity and never exceeds it.
- Prove callback/query duplicate facts do not double-count fill.
- Confirm no unresolved UNKNOWN/MANUAL_REVIEW at terminal.
- Run:

```bash
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/audit_side_effect_calls.py
pytest -q tests/qmt/test_guojin_sim_execution_loop.py tests/qmt/test_guojin_sim_host_oms.py
```

## Exit criteria

- Repaired Host survives real backlog replay and remains leader.
- Fresh exact `.SGT` tick and SHENGANGTONG route evidence are captured.
- Core authorization is accepted with
  `rule_version=guojin-sim-accept-all-v1`.
- Exactly one submit reaches QMT.
- Broker evidence converges to exact `FILLED` once.
- Mutation budget and production-zero boundary hold.
- Standard Agent -> Architect handoff is committed and pushed.
