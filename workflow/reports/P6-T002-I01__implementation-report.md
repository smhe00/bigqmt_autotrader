---
workflow_schema: 1
phase: P6
task_id: P6-T002
iteration: I01
task_key: P6-T002-I01
reply_to: workflow/tasks/P6-T002-I01__guojin-sim-market-open-e2e.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T002-I01__architect-review.md
---

# P6-T002-I01 Implementation Report

## 1. Result

- Status: `REVIEW_READY`
- Runtime result: **PASS candidate with one documented Host/OMS wiring gap**
- Implementation commit: 0a12b622c98ff8819a5dbc66c076653c90850101
- Base commit: 0a12b622c98ff8819a5dbc66c076653c90850101
- Final commit: 0a12b622c98ff8819a5dbc66c076653c90850101
- Runtime start: `2026-09-21 09:15:07 +08:00`
- Mutation window: `2026-09-21 09:30:28` through `09:33:32 +08:00`
- Runtime end / verification complete: `2026-09-21 09:38:38 +08:00`

The market-open simulation run proved submit, exact-token cancel, fill, broker rejection,
Stock Connect routing, deterministic BrokerEvidence/OMS convergence, publisher duplicate
protection and Host restart/replay. Four submit commands and one cancel command were consumed.
There was no UNKNOWN and no production mutation.

The generic Host process is intentionally constructed without the Guojin mapper or an OMS sink.
It therefore quarantined the 12 raw ORDER/DEAL callback rows fail-closed. The same durable raw
events were replayed through the pinned `GuojinSimEvidenceMapper` and an in-memory persistent OMS
schema; every calibrated row converged as expected. This proves the mapper/OMS contract but also
identifies a remaining integration gap before the default Host can claim live OMS ingestion.

## 2. Runtime identity

```text
terminal_instance_id = guojin_sim
execution_mode = SIMULATION_CALIBRATION
simulation_only = true
bridge_build = p5-simulation-calibration-7
account_fingerprint_hash = sha256:ff266d...ce0702
qmt_session_id_redacted = 3a958a...12bd9
host_simulation_authorization = --allow-simulation-mutation
manifest/account/session pin = MATCH
live_submit/live_cancel = true/true (simulation instance only)
bridge submit/cancel fuse = 2000/2000
```

The manifest and matching-session `bridge_ready` agreed on instance, account type `STOCK`,
fingerprint, build, mode and session. Read-only account discovery also reported `STOCK`,
`HUGANGTONG` and `SHENGANGTONG` capability records.

## 3. Baseline snapshot

At `09:30:08.504 +08:00`, active query sequence 926 was healthy and current-day:

```text
trading_date = 20260921
account rows = 1
position rows = 2 (510300.SH and 511010.SH)
order rows = 0
deal rows = 0
query_errors = 0
read_model_healthy = true
510300.SH exact active-query last_price = 4.597
```

No account number, full fingerprint, full session ID or private terminal path is included here.

## 4. Scenario evidence

| Scenario | Symbol | Side/Qty | Intent | Broker raw status | BrokerEvidence / OMS | Result |
|---|---|---:|---|---|---|---|
| S1 passive/cancel | 510300.SH | BUY 100 @ 4.40 | Rest below exact 4.597 quote, then exact cancel | ORDER `50/51` -> `50/51` -> `54/51` | `ORDER_ACCEPTED -> ACKNOWLEDGED -> ORDER_CANCELLED -> CANCELLED` | PASS |
| S2 fill | 510300.SH | BUY 100 @ 4.65 | Marketable bounded LIMIT | ORDER `50/51` -> `50/51` -> `56/51`; DEAL 100 @ 4.602 | `ORDER_ACCEPTED -> ACKNOWLEDGED -> FULL_FILL -> FILLED`; DEAL replay duplicate ignored | PASS |
| S3 duplicate/idempotency | S1 cancel target | exact same client/order identity | Repeat cancel publication | Publisher rejected because identical durable cancel already existed | Broker mutation count unchanged; evidence duplicate protection also ignored DEAL after terminal FULL_FILL | PASS |
| S4 restart/recovery | all prior | no new command | Host restart after all states known | Recovery snapshot seq 926; replayed 63 through seq 988, then caught up to 990 | healthy current-session replay; no command republished; submit/cancel totals stayed 4/1 | PASS |
| S5 Stock Connect | 00700.HGT | BUY 100 @ 1.00 | Bounded route exercise | ORDER `50/51` -> `56/51`; DEAL 100 @ 1.00 | `ORDER_ACCEPTED -> ACKNOWLEDGED -> FULL_FILL -> FILLED`; DEAL duplicate ignored | PASS, simulation route behavior |
| S6 invalid lot | 510300.SH | BUY 1 @ 4.65 | Natural broker rejection | ORDER transient `50/51`, then `57/51`; counter reports buy-unit 100 | `ORDER_REJECTED -> REJECTED` | PASS |

### S1 identity and timing

```text
client_order_id = p6t002-s1-passive-20260921
submit command_id = d60406740d364465ac679fe8bbf5d350
cancel command_id = simcancel-4eb447c2ec7d6ee96e5a59223e9eae59
broker_token = BQc8e6...52d9
broker_order_id = ...949
seq 933  09:30:28.549  SIMULATION_SUBMIT_CALL_RETURNED
seq 934  09:30:30.679  transient ORDER 50/51 without settled broker identity (rejected by mapper)
seq 935  09:30:30.968  ORDER 50/51, active and exact-token matched
seq 945  09:30:53.512  SIMULATION_CANCEL_SIGNAL_SENT
seq 946  09:30:53.729  ORDER 54/51, cancelled
active query seq 1027 = status 54, cancelled_quantity 100
```

One deterministic cancel command targeted one broker ID and one broker token. Re-running the same
publisher request failed before spool publication with `cancel already published`; no second broker
cancel was possible.

### S2 identity and timing

```text
client_order_id = p6t002-s2-fill-20260921
command_id = 00701ce6ca114253aed7024279a65d2f
broker_token = BQ324b...cb21
broker_order_id = ...1094
seq 956  09:31:19.510  SIMULATION_SUBMIT_CALL_RETURNED
seq 958  09:31:19.701  ORDER 50/51, accepted
seq 960  09:31:19.852  ORDER 56/51, full fill 100
seq 962  09:31:19.942  DEAL 100 @ 4.602
active query seq 1027 = ORDER 56/51 + DEAL 100 @ 4.602
```

### S5/S6 identity and timing

```text
S5 command_id = 0214bc49813c495c8eea1142458c78ff
S5 broker_token / broker_order_id = BQ495a...9a71 / ...1
S5 seq 977/978/979 = accepted / full fill / deal

S6 command_id = 430e1570167b415eb43a69d4d89e0fc3
S6 broker_token / broker_order_id = BQ7273...9176 / ...0793
S6 seq 1002 = ORDER 57/51, rejected for invalid buy unit
active query seq 1027 = S6 rejection preserved with no fill
```

The HGT callbacks were internally consistent and token matched, but the selected `STOCK` active
query did not include the HGT order/deal. This is expected evidence that linked-account active-query
coverage must be completed before Stock Connect production reconciliation can rely on snapshots.

## 5. BrokerEvidence and OMS replay

The exact durable callback files from sequences 933-1027 were replayed without broker mutation.
The mapper was registered only with the four durable command identities, and the OMS used the
current SQLite schema in memory. Results:

```text
S1: seq 935 ORDER_ACCEPTED APPLIED; seq 946 ORDER_CANCELLED APPLIED; final CANCELLED
S2: seq 958 ORDER_ACCEPTED APPLIED; seq 960 FULL_FILL APPLIED;
    seq 962 FULL_FILL DUPLICATE_IGNORED; final FILLED
S5: seq 977 ORDER_ACCEPTED APPLIED; seq 978 FULL_FILL APPLIED;
    seq 979 FULL_FILL DUPLICATE_IGNORED; final FILLED
S6: seq 1002 ORDER_REJECTED APPLIED; final REJECTED
```

Transient callback rows 934, 957 and 1001 lacked a settled broker ID/remaining quantity and were
rejected as `ORDER_ACCEPTED_NOT_SETTLED`; later calibrated rows converged cleanly. No identity
conflict, overfill, unexplained duplicate or UNKNOWN was observed.

## 6. Mutation accounting

```text
guojin_sim submit commands = 4
guojin_sim cancel commands = 1
broker passorder calls observed = 4
broker cancel calls observed = 1
processed task command files = 5
rejected/unknown task command files = 0/0
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
```

## 7. Recovery / duplicate audit

- Host was stopped only after S1/S2/S5 were terminal and no UNKNOWN existed.
- Restart used the same manifest-pinned instance and current QMT session.
- Recovery selected snapshot sequence 926, replayed 63 events through sequence 988 and caught up
  through sequence 990 with `read_model_healthy=true`.
- Existing processed command files remained in `processed`; inbox/claimed/unknown were empty.
- No command was automatically republished and QMT mutation counters did not increase.
- Duplicate cancel publication was rejected by the simulation publisher before spool write.
- Duplicate terminal fill evidence was `DUPLICATE_IGNORED`, not applied twice.

## 8. Runtime defects and fixes

No product code was changed in this runtime-only task.

One integration gap was observed: `qmt.host` constructs bare `QmtHostIngestion()` and therefore
does not attach `GuojinSimEvidenceMapper`, a durable OMS repository, or an evidence sink. Its
fail-closed behavior quarantined 12 ORDER/DEAL callback rows while keeping the read model healthy.
The versioned mapper and OMS themselves passed exact-event replay. A later implementation task
should wire these components only for a manifest-pinned `guojin_sim` runtime and persist durable
command identity registration before enabling this path. It must retain the current fail-closed
behavior for all other instances and preserve UNKNOWN/no-blind-retry rules.

The Stock Connect callback path also lacks matching linked-account active-query rows in the selected
`STOCK` snapshot. Do not treat the simulation HGT fill as production route proof.

## 9. Verification

```text
python tools/verify_workflow_contract.py: PASS
pytest -q: PASS (416 passed in 59.78s)
python tools/audit_side_effect_calls.py: PASS
python tools/build_qmt_deployments.py --check: PASS
python tools/verify_bridge_protocol_exhaustive.py: PASS (4608 transitions + spool checks)
python tools/verify_bridge_schema_contract.py: PASS
python tools/verify_broker_evidence_contract.py: PASS (7200 cases)
formal/TLC if applicable: NOT REQUIRED (no code/FSM/recovery semantic change)
```

The src-layout verifiers and pytest were invoked with the repository `src` directory on Python's
import path. The first root-level invocation of three src imports failed only because the package is
not installed in that interpreter; corrected invocations above all passed.

## 10. Safety declaration

```text
simulation account only = YES
production guojin passorder/cancel executed = NO
Galaxy mutation executed = NO
generic production mutation executed = NO
blind retry after UNKNOWN = NO
unresolved active simulation order remains = NO
unresolved UNKNOWN remains = NO
```

## 11. Deviations / blockers

1. The default Host did not ingest broker evidence into OMS live; it quarantined raw execution rows
   by design. Deterministic replay proved the mapper/OMS outcome, but runtime wiring remains a Gate.
2. HGT ORDER/DEAL callbacks were terminal, while the `STOCK` active query omitted the HGT rows.
   Linked-account query reconciliation remains incomplete.
3. No natural partial fill occurred within the bounded quantity budget. This was optional and was
   not manufactured with a larger order.

There is no user-action blocker, no login/captcha blocker and no production exposure.

## 12. Recommended next Gate

Create a narrowly scoped Architect-authorized implementation task to connect manifest-pinned
`guojin_sim` durable command registration, `GuojinSimEvidenceMapper`, persistent OMS evidence sink
and restart replay. Add linked-account active query reconciliation for HGT/SGT. Then repeat S1/S2
with live `evidence_ingested=true`, zero semantic quarantine for calibrated rows, and durable OMS
state surviving Host restart. Do not broaden production authority.

## 13. Handoff

Prepared with:

```bash
python tools/agent_workflow_handoff.py --implementation-commit 0a12b622c98ff8819a5dbc66c076653c90850101
python tools/verify_workflow_contract.py
```

Only this report and `WORKFLOW_STATE.yaml` are included in the Agent -> Architect handoff commit.
