---
workflow_schema: 1
phase: P6
task_id: P6-T006
iteration: I01
task_key: P6-T006-I01
reply_to: workflow/tasks/P6-T006-I01__guojin-sim-oms-marketable-fill-runtime.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T006-I01__architect-review.md
---

# P6-T006-I01 Implementation Report

## Result
- Status: `REVIEW_READY`
- Runtime date/time: 2026-09-22 11:09:52--11:10:12 Asia/Shanghai (03:09:52--03:10:12 UTC)
- Implementation commit: 573fbc99fddc44a9ec356ee23ae7a961faadb7dc

## Preflight
- Verified the sole mutation target before dispatch from `D:\BigQMTData\spool\guojin_sim\instance.json`: `terminal_instance_id=guojin_sim`, `execution_mode=SIMULATION_CALIBRATION`, `simulation_only=true`, `bridge_build=p5-simulation-calibration-7`, session `a699da30438c44c3bfe55c4d8a0ab214`, and fingerprint `sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702`.
- The simulation Host was started with `--allow-simulation-mutation`; its OMS leader lease was cleanly transferred to the one-shot OMS execution runtime for dispatch, then restored to Host for broker-evidence reconciliation.
- Read model was healthy, no unresolved `UNKNOWN` or `MANUAL_REVIEW` existed. Fresh QMT snapshot sequence 1968 showed `510300.SH` sellable quantity 400 and last price 4.64.
- No production `guojin`, `galaxy`, or generic command spool was written.

## Marketable submit
- Scenario: `SELL 100 510300.SH LIMIT 4.50`. The 4.50 limit was below the current 4.64 quote, making it marketable while remaining within the current price-range risk snapshot (4.17--5.10).
- `client_order_id`: `p6t006-marketable-sell-510300-20260922`; deterministic risk decision: accepted, `RISK_OK`.
- One immutable OMS dispatch was persisted and published:
  - command ID: `simoms-1973218cfbc1db02305c4f64c882868a807474d5985d2234` (`SUBMIT_LIMIT`)
  - broker token: `BQe0783c4595e63d8fe00c`
  - frame digest: `sha256:9cd9607f72a389d69a9b8cd4e1160b9f1cfb53df9bfaae8ea2ceca807ad2c672`
  - published 03:09:52.357762 UTC, reached `guojin_sim/commands/processed`, durable dispatch state `OBSERVED_PROCESSED`.
- QMT sequence 1983 reported `SIMULATION_SUBMIT_CALL_RETURNED`; it remained a control-plane result and was recorded `DUPLICATE_IGNORED`, not used as fill truth.

## BrokerEvidence -> FILLED
- Initial transient ORDER at sequence 1984 had no broker order ID and was quarantined. It made no OMS lifecycle change.
- Trusted ORDER at sequence 1985 carried broker order ID `3346`, order ref `446149875865646903`, exact remark/token, raw `status_code=50`, `submit_status_code=51`, quantity 100, fill 0, and remaining 100. Calibrated `BrokerEvidence ORDER_ACCEPTED` advanced to `ACKNOWLEDGED`.
- Trusted ORDER at sequence 1987 carried the same identity and raw `status_code=56`, `submit_status_code=51`, fill 100, remaining 0. It emitted `BrokerEvidence FULL_FILL` and advanced the OMS to `FILLED`.
- DEAL at sequence 1989 independently carried the same token/order ref, broker order ID `3346`, trade ID `50031422`, quantity 100, and price 4.641. It emitted a second, independent `BrokerEvidence FULL_FILL` observation.
- Final durable OMS row: `FILLED`, broker order ID `3346`, cumulative filled quantity 100/100. State journal: `CREATED -> RISK_ACCEPTED -> SUBMITTING -> UNKNOWN -> RECONCILING -> ACKNOWLEDGED -> FILLED`.

## Idempotency
- There is exactly one `SUBMIT_LIMIT` dispatch for this client order and one processed submit command frame.
- `SIMULATION_SUBMIT_CALL_RETURNED` did not create broker state. The two full-fill facts (ORDER then DEAL) resulted in one `BROKER_EVIDENCE_FULL_FILL` `APPLIED` transition and then one `DUPLICATE_IGNORED` transition while already `FILLED`; cumulative fill remains exactly 100.
- No duplicate submit, no retry after the normal dispatch `UNKNOWN -> RECONCILING` boundary, and no cancel command were issued.

## Mutation accounting
```text
guojin_sim submits = 1
guojin_sim cancels = 0
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
UNKNOWN blind retries = 0
```

## Verification
- Runtime reconciliation: PASS. The broker ORDER and DEAL evidence exactly matched the persisted token/identity and converged to `FILLED`; no quarantine item advanced OMS state.
- Local CI-equivalent Python test suite: `453 passed in 11.17s`.
- Local gates: `verify_fsm_exhaustive.py` PASS (196 pairs), `verify_bridge_protocol_exhaustive.py` PASS (4608 transitions), `verify_bridge_schema_contract.py` PASS, `verify_broker_evidence_contract.py` PASS (7200 cases), `audit_side_effect_calls.py` PASS, `build_qmt_deployments.py --check` PASS.
- GitHub CI/TLC: pending push of this Agent handoff commit.

## Deviations / blockers
- NONE. The expected first no-broker-ID transient ORDER was quarantined and did not require or cause a retry.

## Handoff
Prepared for standard Agent -> Architect handoff after committing this report and control-state update together.
