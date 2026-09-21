---
workflow_schema: 1
phase: P6
task_id: P6-T003
iteration: I01
task_key: P6-T003-I01
state: AGENT_READY
owner: agent
audit_base_commit: 3fd8dc73df986922521d8da1bef3f7b7e75f20c9
expected_report: workflow/reports/P6-T003-I01__implementation-report.md
expected_review: workflow/reviews/P6-T003-I01__architect-review.md
---
# P6-T003-I01 — Guojin Simulation Host/OMS Integration

## Objective

Close the two gaps exposed by P6-T002 without broadening production authority:

1. For the manifest-pinned `guojin_sim` instance only, wire durable command identity registration, `GuojinSimEvidenceMapper`, persistent OMS evidence ingestion, snapshot evidence reconciliation, and restart recovery into the normal Host path.
2. Extend read-only linked-account active-query reconciliation so HGT/SGT ORDER/DEAL evidence can be reconciled rather than relying only on callbacks.
3. Re-run bounded market-hours simulation validation and prove live `evidence_ingested=true`, durable OMS terminal state across Host restart, and no semantic quarantine for calibrated settled rows.

## Hard safety boundary

Broker mutation remains authorized **only** for `guojin_sim` (`SIMULATION_CALIBRATION`, `SIMULATION_ONLY=true`, existing pinned fingerprint/build/session contract). Production `guojin`, Galaxy and generic mutation remain forbidden. Do not modify production LIVE_CANARY authority in this task.

Within `guojin_sim`, Agent may autonomously submit/cancel/retry after understood terminal/rejected outcomes, choose symbols/side/price/quantity, and restart Host/bridge. Maximum additional runtime budget: 12 submits and 12 cancels; LIMIT only; quantity <=100 and broker lot rules apply. Never blind-retry UNKNOWN.

## Required implementation properties

### A. Durable command identity registration

The mapper must not learn identity from an untrusted callback. Reconstruct/register `client_order_id`, broker token, symbol and quantity only from durable command records that passed the existing account/session/simulation authorization boundary. Registration must survive Host restart and replay deterministically.

Conflicting token/client/symbol/quantity identity must fail closed and must not mutate OMS.

### B. Instance-scoped Host wiring

Create mapper/sink wiring only after Host has resolved a valid instance and only when all of these hold:

- `instance_id == guojin_sim`;
- `execution_mode == SIMULATION_CALIBRATION`;
- `simulation_only == true`;
- explicit `--allow-simulation-mutation` is present;
- manifest fingerprint/session/build validation has passed.

For generic, Galaxy, production Guojin, TCP/no-instance mode, or any mismatch, preserve the current fail-closed behavior. No implicit mapper activation.

### C. Persistent OMS

Use the repository's existing durable OMS repository/schema rather than inventing a parallel state store. BrokerEvidence ingestion must be idempotent and survive Host restart. Replaying the same ORDER/DEAL/snapshot evidence must not double-apply fills or terminal transitions.

Do not store secrets or full account identifiers in Git.

### D. Snapshot / linked-account reconciliation

Wire `GuojinSimEvidenceMapper.map_snapshot` for active-query snapshots where applicable. Complete the read-only query path needed to observe linked HUGANGTONG/SHENGANGTONG ORDER/DEAL rows while keeping the selected STOCK account identity contract explicit. If QMT requires per-account-type queries, model them explicitly rather than merging identities by guesswork.

Callback and active-query evidence for the same broker event must deduplicate semantically in OMS.

### E. Quarantine semantics

Calibrated settled rows for registered commands should produce `evidence_ingested=true` and not be semantically quarantined. Transient/unsettled or unregistered rows must continue to fail closed. Do not weaken `ORDER_ACCEPTED_NOT_SETTLED`, token, broker-order-ID, overfill, account, instance, or status-shape checks merely to reduce quarantine count.

### F. Tests / failure injection

Add regression tests for at least:

- mapper/sink enabled only for exact `guojin_sim` authorized instance;
- all other instances remain fail-closed;
- durable identity reconstruction across Host restart;
- conflicting durable identity rejected;
- callback ACK/FILL/CANCEL/REJECT -> persistent OMS transitions;
- callback + snapshot duplicate evidence does not double-apply;
- unregistered token and malformed/transient callback remain quarantined;
- linked HGT/SGT query rows preserve account/route identity;
- restart/replay produces identical OMS state;
- UNKNOWN/no-blind-retry safety unchanged.

Run all existing formal/contract/side-effect tests. If implementation changes an FSM transition, run the applicable formal/TLC gate.

## Runtime validation

After code and CI-equivalent local verification pass, and only during a valid market window, run a minimal simulation-only retest:

1. passive A-share/ETF LIMIT -> broker ACK -> exact-token cancel -> OMS CANCELLED;
2. marketable bounded LIMIT -> broker fill -> OMS FILLED;
3. Host restart -> persistent OMS state unchanged and no command replay;
4. HGT/SGT route if available -> callback plus linked-account active-query reconciliation.

If a market window is unavailable, complete implementation/offline replay tests and leave runtime retest explicitly pending; do not use production as fallback.

## Verification

At minimum run:

```bash
python tools/verify_workflow_contract.py
pytest -q
python tools/audit_side_effect_calls.py
python tools/build_qmt_deployments.py --check
python tools/verify_bridge_protocol_exhaustive.py
python tools/verify_bridge_schema_contract.py
python tools/verify_broker_evidence_contract.py
```

## Report

Update only `workflow/reports/P6-T003-I01__implementation-report.md` for the Agent report. Include changed files/commits, architecture of identity reconstruction and persistent OMS wiring, test results, runtime evidence if executed, mutation counts, quarantine counts/reasons, restart result, linked-account query result, and explicit zero production mutation declaration.

When complete use the repository Agent handoff tool, set REVIEW_READY, and do not create the next task or edit Architect review.
