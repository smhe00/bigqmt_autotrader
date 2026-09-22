---
workflow_schema: 1
phase: P6
task_id: P6-T005
iteration: I01
task_key: P6-T005-I01
reply_to: workflow/tasks/P6-T005-I01__guojin-sim-oms-passive-submit-cancel-runtime.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T005-I01__architect-review.md
---

# P6-T005-I01 Implementation Report

## Result
- Status: `REVIEW_READY`
- Runtime date/time: 2026-09-22 10:40:15--10:43:54 Asia/Shanghai (02:40:15--02:43:54 UTC)
- Local implementation commit: 6d2d66bcb1941bf68c9c38070d0a350769f2e0f9 (no product-code change was required for this runtime gate)
- Final commit: 6d2d66bcb1941bf68c9c38070d0a350769f2e0f9

## Preflight

- Verified the only mutation target from `D:\BigQMTData\spool\guojin_sim\instance.json` before the order: `terminal_instance_id=guojin_sim`, `execution_mode=SIMULATION_CALIBRATION`, `simulation_only=true`, `bridge_build=p5-simulation-calibration-7`, session `a699da30438c44c3bfe55c4d8a0ab214`, account fingerprint `sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702`.
- Host was started only for that instance with `--allow-simulation-mutation`; the OMS leader lease was held by that Host during reconciliation.
- Fresh snapshot/read model was healthy. `510300.SH` had sellable quantity 400 and last price 4.646 before the scenario; no unresolved `UNKNOWN` or `MANUAL_REVIEW` was present.
- No command was published to production `guojin`, `galaxy`, or generic spool roots.

## Passive submit -> ACK
- Scenario: `SELL 100 510300.SH LIMIT 4.700` — deliberately above the observed 4.646 last price, so the order was passive.
- `client_order_id`: `p6t005-passive-sell-510300-20260922`; deterministic risk decision: `RISK_OK` / accepted.
- OMS immutable submit dispatch:
  - command: `simoms-4c467856c576f879709b6f0259f410c5c4647b2a6dfb4485` (`SUBMIT_LIMIT`)
  - broker token: `BQf38a4d42af9f48fa07f1`
  - frame digest: `sha256:be9674ed2cbe9fef5789e11dc7ba3d015be5efb0532c131a376ec649edc0fa11`
  - published 02:40:15.924949 UTC and reached `commands/processed`; durable dispatch state `OBSERVED_PROCESSED`.
- Control-plane result at QMT sequence 1606 was `SIMULATION_SUBMIT_CALL_RETURNED`. It left the OMS in reconciliation and was recorded as `DUPLICATE_IGNORED`; it did not ACK the order.
- The first raw transient ORDER without broker ID was quarantined. The next calibrated ORDER evidence (QMT sequence 1608) carried broker order ID `2776`, exact remark/token `BQf38a4d42af9f48fa07f1`, `filled_quantity=0`, `remaining_quantity=100`, and `submit_status_code=51`.
- Its calibrated `BrokerEvidence ORDER_ACCEPTED` advanced the OMS only once: `CREATED -> RISK_ACCEPTED -> SUBMITTING -> UNKNOWN -> RECONCILING -> ACKNOWLEDGED`. A repeated accepted observation was classified `DUPLICATE`.

## Exact cancel -> CANCELLED
- The OMS-owned cancel read trusted persistent broker order ID `2776` and the exact persisted token `BQf38a4d42af9f48fa07f1`; no caller-supplied identity was accepted.
- Exactly one cancel was published:
  - command: `simoms-c2787927fe547c58769d82fa0d76932ceb07a1ccff40998a` (`CANCEL_ORDER`)
  - frame digest: `sha256:5ef2e2b0b5ddf145d56250f8bd2ab3703cb691fcf3e0a9b98ccc1e56ac3510dd`
  - broker order ID: `2776`; published 02:41:50.026698 UTC and reached `commands/processed`; durable dispatch state `OBSERVED_PROCESSED`.
- QMT control-plane result at sequence 1634 was `SIMULATION_CANCEL_SIGNAL_SENT`; it remained control-plane only and did not itself create `CANCELLED`.
- Calibrated raw ORDER at sequence 1635 carried broker order ID `2776`, exact remark/token, `status_code=54`, `filled_quantity=0`, `remaining_quantity=100`. It emitted `BrokerEvidence ORDER_CANCELLED` and advanced `ACKNOWLEDGED -> CANCEL_PENDING -> UNKNOWN -> RECONCILING -> CANCELLED` once. The later equivalent evidence was a `SEMANTIC_DUPLICATE`.
- Final durable OMS state: `CANCELLED`, broker order ID `2776`, filled quantity `0`; no blind retry and no second cancel were issued.

## Mutation accounting
```text
guojin_sim submits = 1
guojin_sim cancels = 1
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
UNKNOWN blind retries = 0
```

## Verification
- Local targeted runtime reconciliation: PASS; both QMT command frames were found only in the authorized `guojin_sim/commands/processed` spool, and the OMS journal recorded one broker-evidence ACK and one broker-evidence CANCELLED transition.
- Local CI-equivalent Python suite: `453 passed in 13.04s`.
- Local gates: `verify_fsm_exhaustive.py` PASS (196 pairs), `verify_bridge_protocol_exhaustive.py` PASS (4608 transitions), `verify_bridge_schema_contract.py` PASS, `verify_broker_evidence_contract.py` PASS (7200 cases), `audit_side_effect_calls.py` PASS, `build_qmt_deployments.py --check` PASS.
- GitHub CI/TLC: pending push of this Agent handoff commit.

## Deviations / blockers
- NONE. The expected initial no-broker-ID transient ORDER was quarantined, not admitted as broker evidence. This did not require a retry.

## Handoff
Prepared for standard Agent -> Architect workflow handoff after committing this report and the control-state update together.
