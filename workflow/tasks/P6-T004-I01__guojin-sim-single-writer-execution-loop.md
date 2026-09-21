---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I01
task_key: P6-T004-I01
state: AGENT_READY
owner: agent
audit_base_commit: de45b30b10c934ec4dab146b29d38169476d797a
expected_report: workflow/reports/P6-T004-I01__implementation-report.md
expected_review: workflow/reviews/P6-T004-I01__architect-review.md
---

# P6-T004-I01 — Guojin Simulation Single-Writer Execution Loop

## Objective

Close the remaining simulation execution gap:

```text
typed OrderIntent
    -> deterministic Risk evaluation
    -> persistent OMS
    -> durable deterministic QMT command
    -> guojin_sim broker mutation
    -> ORDER/DEAL/query BrokerEvidence
    -> persistent OMS terminal state
```

The normal path must no longer depend on a human manually calling `simulation_probe.py` for each
order.

This task is **simulation-only**. It does not authorize production Guojin, Galaxy or generic
mutation.

## Architectural hard constraint: one OMS writer

`GuojinSimOmsRuntime` / Host owns `host_oms.sqlite3` and its singleton LeaderCoordinator lease.

Do **not** instantiate a second `OfflineOms` or second write leader against that database.

Reuse/refactor existing deterministic risk, repository, state-machine, evidence and leader
components under the Host-owned lease. If common logic must be extracted from `OfflineOms`,
extract reusable pure/service logic rather than running two leaders.

Every OMS mutation and every order-dispatch decision must be fenced by the current Host lease.

## A. Public simulation execution API

Add a typed API owned by the authorized `guojin_sim` OMS runtime that accepts:

- `OrderIntent`;
- `RiskSnapshot`;
- `RiskPolicy`.

The API itself must call the existing deterministic risk engine. A caller may not pass a
pre-accepted `RiskDecision` as execution authority.

Required behavior:

- risk reject -> persist intent + rejected decision; publish **zero** QMT commands;
- risk accept -> persist intent + accepted decision and proceed to durable dispatch;
- `RuntimeMode.LIVE_ARMED`, disabled mode, fingerprint mismatch, stale data, invalid lot/price
  etc. continue to fail before QMT command publication under existing P2 rules.

Do not weaken the current P2 policy boundary.

## B. Deterministic durable dispatch

Create a durable dispatch record using the existing OMS database. Do not create an independent
lifecycle database.

For every submit, derive deterministic immutable identities from the authorized account +
client_order_id, including:

- command_id;
- broker_token;
- exact command frame digest;
- QMT session;
- symbol/side/quantity/limit price;
- dispatch state.

Use `QmtCommandSpool` for publication.

The same client/order must map to the same command identity and identical frame. Re-execution of
the same operation is idempotent; a different frame under the same identity is a hard conflict.

### Crash-window rule

SQLite and filesystem publication cannot be one transaction, so recovery must explicitly handle
every boundary:

1. durable dispatch plan committed, command absent from all known spool states:
   - safe to publish exactly once using deterministic command_id if no evidence shows prior crossing;
2. identical command exists in inbox/claimed/processed/rejected/unknown:
   - never create a second command;
   - reconcile local dispatch state to that exact durable frame;
3. conflicting command frame:
   - fail closed / manual review;
4. command may have crossed the broker boundary or is UNKNOWN:
   - **never auto-resubmit**;
5. absence cannot be proven because of archive/history ambiguity:
   - fail closed; do not guess.

Add explicit failure-injection tests for each crash boundary.

## C. Broker lifecycle remains evidence-owned

QMT `command_result` is control-plane dispatch evidence only.

For `SIMULATION_CALIBRATION`, support/record the required command-result statuses if needed, but:

- `SIMULATION_SUBMIT_CALL_RETURNED` must not create ACK;
- cancel signal return must not create CANCELLED;
- only calibrated ORDER/DEAL/active-query BrokerEvidence may move broker lifecycle to
  ACKNOWLEDGED/PARTIALLY_FILLED/FILLED/CANCELLED/REJECTED.

Preserve semantic deduplication from P6-T003.

## D. Cancel through the same OMS-owned path

Add exact cancel orchestration for an existing non-terminal order.

Requirements:

- broker_order_id and broker_token must come from trusted persistent OMS identity/evidence;
- deterministic cancel command id;
- exact token-matched cancel;
- duplicate invocation is idempotent and cannot issue repeated broker cancel;
- ambiguous/UNKNOWN state blocks automatic repeat cancel;
- terminal order returns a no-op/terminal result without broker mutation.

Manual `simulation_probe cancel` remains a diagnostic escape hatch, not the normal path.

## E. Session rollover / restart

Integrate with the P6-T003 rollover guard:

- old Host session never publishes a new-session order;
- first new-session event is retained;
- after restart, persistent intents/risk/dispatch/evidence are recovered under the new lease;
- already published/processed commands are never automatically reissued;
- a pending pre-publication dispatch may be completed only when exact absence is provable under
  section B.

No blind broker retry.

## F. Instance and authority boundary

Execution API must exist only when all current P6-T003 authorization conditions are true:

```text
instance_id == guojin_sim
execution_mode == SIMULATION_CALIBRATION
simulation_only == true
--allow-simulation-mutation present
authorized fingerprint matches
authorized build matches
current QMT session matches
Host leader lease held
```

For production `guojin`, Galaxy, generic, TCP/no-instance mode, or any mismatch:

```text
submit commands = 0
cancel commands = 0
```

Do not modify production LIVE_CANARY authority.

## G. Tests / formal safety

At minimum add regression/failure-injection coverage for:

- exact authorized runtime can submit after risk ACCEPT;
- risk REJECT produces zero spool command;
- caller cannot bypass risk with an external accepted decision;
- same intent repeated -> one deterministic submit command;
- same command id + different frame -> hard conflict;
- crash before publish -> deterministic safe completion only if absence is provable;
- crash after publish before DB acknowledgement -> no duplicate publish;
- claimed/processed/unknown existing frame -> no re-submit;
- UNKNOWN -> no blind retry;
- exact cancel once; duplicate cancel does not repeat broker mutation;
- terminal cancel no-op;
- command_result cannot fabricate broker ACK/CANCEL/FILL;
- callback/query evidence still drives terminal state;
- Host restart preserves intent/risk/dispatch/OMS state;
- session rollover fail-close unchanged;
- production/Galaxy/generic authority remains zero;
- leader fencing prevents a second writer.

If the dispatch/recovery state machine introduces new states or transitions, add/update the
applicable formal/TLA+ model rather than relying only on unit tests.

## H. Runtime validation

Today is after the regular 2026-09-21 market window. Complete implementation and offline/CI
verification now.

At the next valid market window, run a minimal `guojin_sim` validation through the **new OMS
execution API**, not manual simulation_probe as the primary submit path:

1. one risk-rejected intent -> verify zero command;
2. one passive supported A-share/ETF LIMIT -> ACK -> OMS-owned exact cancel -> CANCELLED;
3. one bounded marketable LIMIT -> ORDER/DEAL -> FILLED;
4. Host restart -> persistent terminal states unchanged, zero command replay;
5. if linked route is available, one HGT/SGT simulation order through the same API.

Within `guojin_sim`, Agent may autonomously choose symbol/price/side/quantity and submit/cancel
for these tests. LIMIT only, quantity <=100, no user confirmation required. Do not use production
as fallback.

If no market window is available before handoff, offline PASS may be reported with runtime marked
pending; do not weaken safety to force runtime completion.

## Required verification

```bash
python tools/verify_workflow_contract.py
pytest -q
python tools/audit_side_effect_calls.py
python tools/build_qmt_deployments.py --check
python tools/verify_bridge_protocol_exhaustive.py
python tools/verify_bridge_schema_contract.py
python tools/verify_broker_evidence_contract.py
```

Run all applicable formal/TLC gates when dispatch/recovery semantics change.

## Report

Update only:

```text
workflow/reports/P6-T004-I01__implementation-report.md
```

Include:

- changed files/commits;
- single-writer architecture;
- exact dispatch persistence schema/state;
- deterministic command-id/frame rules;
- crash-window matrix and test result;
- risk ACCEPT/REJECT behavior;
- submit/cancel idempotency behavior;
- command_result vs BrokerEvidence boundary;
- restart/session-rollover behavior;
- runtime evidence if available;
- mutation counts;
- explicit production Guojin/Galaxy/generic mutation = 0;
- CI/formal results;
- unresolved blockers.

When complete, use `tools/agent_workflow_handoff.py`; do not edit Architect review or create the
next task.
