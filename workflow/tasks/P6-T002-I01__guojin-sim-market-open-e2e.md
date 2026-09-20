---
workflow_schema: 1
phase: P6
task_id: P6-T002
iteration: I01
task_key: P6-T002-I01
state: AGENT_READY
owner: agent
issued_date: 2026-09-20
scheduled_execution: 2026-09-21T09:30:00+08:00
audit_base_commit: c8066c98cc0cc2d88630830c2cd030f4289f7e0d
expected_report: workflow/reports/P6-T002-I01__implementation-report.md
expected_review: workflow/reviews/P6-T002-I01__architect-review.md
---

# P6-T002-I01 — Guojin Simulation Market-Open E2E Runtime Test

## 1. Objective

At **2026-09-21 09:30 Asia/Shanghai (Monday)**, use the existing fingerprint-pinned
`guojin_sim` simulation account with **real market data / real market hours** to exercise as
much of the end-to-end execution and reconciliation path as can be safely validated.

This is a **simulation-account runtime test**, not a production-account canary.

Primary goals:

1. prove Host -> durable command spool -> QMT bridge -> simulated broker mutation;
2. observe ORDER/DEAL/query callbacks and active-query reconciliation on live market data;
3. validate Broker Evidence mapping and OMS terminal convergence for accepted, cancelled,
   filled and, where naturally available, rejected/partial-fill paths;
4. exercise exact-token cancel and duplicate/retry protections;
5. exercise recovery/restart behavior without producing duplicate simulation broker mutations;
6. collect enough evidence to decide the next Gate without asking the user for routine choices.

## 2. Exact safety boundary

Only this instance is authorized:

```text
TERMINAL_INSTANCE_ID = guojin_sim
EXECUTION_MODE        = SIMULATION_CALIBRATION
SIMULATION_ONLY       = True
BRIDGE_BUILD          = p5-simulation-calibration-7
```

The account fingerprint must match the existing `guojin_sim` manifest and current
`bridge_ready` session.

### Explicit authorization for this task

Within the **Guojin simulation account only**, Agent may autonomously:

- submit orders;
- cancel orders;
- retry a new command after a fully understood fail-closed/rejected outcome;
- change symbol;
- change BUY/SELL direction when holdings/rules permit;
- change quantity;
- change limit price;
- run multiple scenarios;
- restart Host / reload the simulation bridge when required for recovery testing.

No per-order user confirmation is required.

Operational task budget:

```text
max new submit commands for this task = 20
max cancel commands for this task     = 20
quantity per order                    = 1..100, subject to broker/market lot rules
order type                            = LIMIT only
supported symbols                     = six-digit .SH/.SZ or five-digit .HK/.HGT/.SGT
```

The bridge's existing stricter constraints remain authoritative.

### Never authorized

- production `guojin` mutation;
- Galaxy mutation;
- generic production mutation;
- use of `live_canary_probe.py` for this task;
- changing a production fingerprint/build/permission to make a test pass;
- market orders;
- hiding or deleting broker evidence;
- blind retry after UNKNOWN;
- publishing secrets, full account identifiers, local userdata paths or private logs to Git.

If any production instance/fingerprint is selected accidentally, stop mutation immediately,
continue read-only diagnostics, and record the blocker. Do not fall back to production.

## 3. Timing

Today, 2026-09-20, is Sunday. Therefore there is no valid real market window at today's 09:30.

Execution schedule is:

```text
2026-09-21 09:15-09:29 Asia/Shanghai : local preflight/read-only preparation
2026-09-21 09:30 onward              : simulation mutation may begin
09:30-11:30                           : primary morning test window
13:00-15:00                           : continue only if useful scenarios remain
```

Do not publish mutation commands before 09:30:00 Asia/Shanghai.

If the simulation broker or market data service reports the market unavailable, stay simulation-only,
collect diagnostics, run all offline verification possible, and report the exact blocker without
asking the user unless a human-only login/terminal action is strictly required.

## 4. Bootstrap / preflight

Read only through the single bootstrap entrypoint first:

```text
workflow/control/WORKFLOW_STATE.yaml
```

Then:

1. refresh `main` with fast-forward only;
2. verify current `task_key == P6-T002-I01`, `owner == agent`,
   `state in {AGENT_READY, CHANGES_REQUIRED}`;
3. run:
   ```bash
   python tools/verify_workflow_contract.py
   python tools/build_qmt_deployments.py --check
   python tools/audit_side_effect_calls.py
   ```
4. verify the loaded QMT script is exactly:
   `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py`;
5. verify `instance.json` and matching-session `bridge_ready` agree on:
   - `instance_id=guojin_sim`;
   - simulation-only mode;
   - account fingerprint;
   - account type;
   - bridge build;
   - current QMT session;
   - submit/cancel limits;
6. start Host only with explicit simulation authorization
   (`--allow-simulation-mutation`) using the repository's existing CLI;
7. capture a read-only ACCOUNT/POSITION/ORDER/DEAL baseline before the first mutation.

Do not copy sensitive account IDs or local paths into the Git report; use hashes/redacted identity.

## 5. Scenario plan

Agent may adapt symbols/prices based on actual live quotes and broker capability evidence.
Do **not** stop to ask the user to choose routine symbols or prices.

### S1 — passive order -> ACK/active -> exact cancel

Choose a liquid simulation-supported A-share/ETF instrument with exact current quote and valid lot
size. Prefer a symbol already demonstrated by prior calibration if it remains valid.

- submit a bounded passive LIMIT order designed not to cross immediately;
- wait for broker ORDER/query evidence;
- obtain exact broker order ID + broker token;
- cancel using the repository simulation publisher;
- reconcile callback + active query until terminal CANCELLED or a clearly classified terminal state;
- prove one cancel command maps to one exact token-matched broker order.

Required evidence:

```text
client_order_id
command_id
broker_token
broker_order_id
command_result sequence
raw broker ORDER status sequence
BrokerEvidence sequence
OMS state sequence
active query before/after cancel
```

### S2 — bounded fill path

Choose a liquid simulation-supported instrument and use a fresh exact quote.

- submit one LIMIT BUY with quantity <=100 and a price selected to have a high probability of
  filling in the simulation environment without using a market order;
- reconcile ORDER + DEAL + active query to terminal FILLED where the broker supports it;
- if only PARTIAL_FILL occurs naturally, capture it and either cancel the remainder or allow it to
  finish based on current evidence.

Do not manufacture a partial fill with excessive order size; qty remains <=100.

### S3 — duplicate/idempotency protection

After S1/S2 has a fully understood state:

- attempt only protocol-safe duplicate/replay checks that should be rejected/deduplicated before
  causing a second broker mutation;
- verify the broker mutation count does not increase unexpectedly.

Never blind-retry a command whose broker crossing is UNKNOWN.

### S4 — Host/recovery behavior

When there is no unresolved UNKNOWN and the currently selected order is either terminal or its
active state is fully known:

- restart Host and/or reload the simulation bridge as appropriate;
- verify session pinning and orphan/recovery rules;
- verify previously processed commands are not automatically resubmitted;
- capture post-restart active query and reconciliation.

Do not perform a destructive recovery experiment while broker identity is ambiguous.

### S5 — Stock Connect route, if available

After the core A-share scenarios have converged, use the existing read-only route discovery.

Preferred candidate:

```text
00700.HGT
```

If exact route metadata/tick evidence is valid in `guojin_sim`, perform a bounded simulation
LIMIT route test. A passive route/reject is useful evidence; a fill is not required.

If HGT route is unavailable, Agent may try another already-discovered `.HGT/.SGT/.HK` candidate
without user intervention. Do not widen production authority.

### S6 — additional useful coverage

If time remains and all prior scenarios are clean, Agent may use the remaining simulation budget to
cover additional **distinct** state transitions or broker raw statuses. Do not spend mutations merely
to repeat already-proven behavior.

Priority order:

1. new raw status -> mapper evidence;
2. cancel-state variant;
3. natural partial fill;
4. HGT/SGT route variant;
5. restart/reconcile variant.

## 6. Autonomous decision rules

Routine runtime choices do not require user input.

Agent should choose the next action from current broker evidence using these rules:

- exact identity + known state -> continue;
- clean rejection before broker crossing -> may choose a new bounded simulation case;
- known broker rejection -> reconcile, record, then may choose another bounded case;
- active exact-token order -> reconcile or cancel before starting another scenario when practical;
- UNKNOWN after broker crossing -> stop new mutation for the affected session; perform read-only
  reconciliation only;
- identity mismatch / multiple matching orders / unexplained duplicate -> stop mutation and report;
- production instance exposure -> immediate stop; no production fallback.

## 7. Implementation changes

This task is primarily runtime validation.

Do not refactor product code before collecting runtime evidence merely for convenience.

If runtime evidence reveals a clear defect:

1. preserve the evidence;
2. add a minimal failing regression test;
3. implement the narrow fix;
4. run full relevant tests/verifiers;
5. resume **simulation-only** runtime testing if the state is unambiguous and the fix does not
   broaden authority.

No production permission change is allowed in this task.

## 8. Required verification

Before handoff, run at least:

```bash
python tools/verify_workflow_contract.py
pytest -q
python tools/audit_side_effect_calls.py
python tools/build_qmt_deployments.py --check
python tools/verify_bridge_protocol_exhaustive.py
python tools/verify_bridge_schema_contract.py
python tools/verify_broker_evidence_contract.py
```

If code changes touch FSM/recovery semantics, also run all applicable formal/TLC gates available in CI.

## 9. Report requirements

Update only:

```text
workflow/reports/P6-T002-I01__implementation-report.md
```

The report must include:

- exact local start/end timestamps;
- QMT session ID in non-sensitive form;
- confirmed simulation build/mode/fingerprint hash;
- scenario-by-scenario command IDs and redacted broker identity;
- raw ORDER/DEAL statuses observed;
- BrokerEvidence mapping;
- OMS transitions;
- submit/cancel counts actually consumed;
- restart/recovery observations;
- all blockers/failures;
- exact code/test commits if fixes were required;
- explicit declaration that production `guojin` / Galaxy / generic mutation count is zero;
- whether any unresolved active simulation order remains.

Agent should attach concise evidence, not full sensitive raw terminal dumps.

## 10. Exit criteria

PASS candidate requires all of:

1. simulation-only identity/session/build pinning verified;
2. at least one broker-accepted simulation submit observed end-to-end;
3. at least one terminal path reconciled from broker evidence;
4. exact-token cancel tested if an active cancellable order can be created;
5. no unexplained duplicate mutation;
6. restart/recovery produces no automatic duplicate submit;
7. production mutation remains zero;
8. required verification passes;
9. report is `REVIEW_READY`;
10. no unresolved UNKNOWN.

If a market/broker limitation prevents one scenario, do not fail the whole task automatically:
record the exact limitation and maximize all remaining independent coverage.

## 11. Agent -> Architect handoff

After completing the report:

```bash
python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>
python tools/verify_workflow_contract.py
```

Commit implementation/evidence report and `WORKFLOW_STATE.yaml` together.
Do not modify the Architect review file and do not create the next task.
