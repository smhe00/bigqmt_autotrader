---
workflow_schema: 1
phase: P6
task_id: P6-T011
iteration: I02
task_key: P6-T011-I02
state: AGENT_READY
owner: agent
audit_base_commit: 5857fe24d71cecc429dba8acd21ddf34429619f6
expected_report: workflow/reports/P6-T011-I02__implementation-report.md
expected_review: workflow/reviews/P6-T011-I02__architect-review.md
---

# P6-T011-I02 — SGT Linked-Route Fill with Permissive guojin_sim Risk

## Objective

Rerun the SGT linked-route runtime Gate after the explicit simulation-only Risk simplification:

> any structurally valid OrderIntent for the strictly pinned guojin_sim runtime is Risk-accepted, so one .SGT simulation order must traverse SHENGANGTONG and converge to broker-evidence-backed FILLED exactly once.

## New simulation-only Risk rule

Current main includes:

- `613cf1ffea5e18eaa8713c723ca391f376526b87`
- `5857fe24d71cecc429dba8acd21ddf34429619f6`

For `GuojinSimOmsRuntime` only:

- generic Risk findings do not block submit;
- stored Risk decision must be `RISK_OK`;
- rule_version must be `guojin-sim-accept-all-v1`.

The following structural/safety boundaries remain mandatory and are **not** bypassed:

- exact `guojin_sim` terminal;
- `SIMULATION_CALIBRATION`;
- `simulation_only=true`;
- authorized STOCK account fingerprint;
- build `p5-simulation-calibration-8`;
- valid typed OrderIntent;
- intent account fingerprint must match the pinned simulator;
- immutable dispatch / exact-once / broker-token rules;
- bridge quantity/mutation fuses;
- production Guojin/Galaxy/generic authority remains unchanged.

## Runtime preflight

1. pull latest `main`;
2. verify Host is using code containing `guojin-sim-accept-all-v1`;
3. exact manifest/session/build/fingerprint;
4. fresh exact .SGT tick from `snapshot_tick_refresh`;
5. SHENGANGTONG linked route detected;
6. no unresolved UNKNOWN/MANUAL_REVIEW;
7. production roots untouched.

## Scenario

Use a calibrated five-digit `.SGT` symbol with current exact tick evidence.

Use normal typed OMS API:

```text
OrderIntent
 -> guojin_sim permissive Risk decision
 -> atomic OMS dispatch
 -> QMT simulation mutation
 -> ORDER / DEAL / active-query evidence
 -> FILLED
```

Choose side and quantity autonomously, quantity <= 100. Prefer a marketable LIMIT order that can complete promptly. Do not manufacture positions or use production authority.

## Required evidence

Record:

- symbol / side / qty / limit / fresh quote;
- client_order_id;
- stored Risk decision and rule_version;
- immutable command ID;
- broker token;
- frame digest;
- broker_order_id;
- ORDER raw status;
- DEAL raw evidence where available;
- route_account_type = SHENGANGTONG when supplied;
- route_account_fingerprint;
- pinned STOCK OMS fingerprint;
- OMS lifecycle and cumulative fill;
- semantic duplicate handling;
- submit/cancel mutation counts.

## PASS criteria

1. SGT intent is no longer blocked by generic Risk;
2. stored Risk decision is accepted with `guojin-sim-accept-all-v1`;
3. exactly one successful SGT submit identity crosses guojin_sim;
4. SHENGANGTONG route metadata is coherent and subordinate to pinned STOCK authority;
5. broker evidence drives FILLED;
6. cumulative fill equals original quantity exactly once;
7. duplicate ORDER/DEAL/query facts do not double-count;
8. no duplicate submit / blind retry / unresolved UNKNOWN;
9. production Guojin/Galaxy/generic mutation = 0.

## Mutation budget

- guojin_sim submit <= 2;
- guojin_sim cancel <= 1 cleanup only;
- production mutation = 0.

A second submit is allowed only after a proven pre-broker/local rejection or known terminal broker rejection. Never retry after ambiguous broker crossing.

## Scope lock

Runtime validation only. Do not modify Risk, OMS, mapper or bridge code in this iteration.

If a new independent runtime defect appears, preserve evidence and return it for the next narrow iteration.

## Handoff

Complete the matching report and return standard Agent -> Architect `REVIEW_READY`.
