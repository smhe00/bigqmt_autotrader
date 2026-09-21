---
workflow_schema: 1
phase: P6
task_id: P6-T003
iteration: I01
task_key: P6-T003-I01
reply_to: workflow/tasks/P6-T003-I01__guojin-sim-host-oms-integration.md
status: AWAITING_AGENT
owner: agent
review_target: workflow/reviews/P6-T003-I01__architect-review.md
---
# P6-T003-I01 Implementation Report

## Result
- Status: implementation and runtime validation complete; workflow handoff pending a pre-existing contract error in the P6-T002 Architect review.
- Implementation commit: `c8b437a`.
- Follow-up session-rollover guard and runtime report commit: `ae258e8`.
- Base commit: `3fd8dc73df986922521d8da1bef3f7b7e75f20c9`.
- Final handoff commit: pending contract repair; state remains `AGENT_READY`.

## Host/OMS integration
The Host activates the evidence mapper and sink only for the manifest-pinned `guojin_sim` `SIMULATION_CALIBRATION` instance with `simulation_only=true`, its fixed account fingerprint/build, and the explicit `--allow-simulation-mutation` switch. Durable processed/unknown command frames are validated and imported into the existing OMS SQLite database at `D:\BigQMTData\spool\guojin_sim\host_oms.sqlite3`; persisted identities are re-registered across QMT session rollover. Conflicting identity batches fail before OMS import. The mapper never learns identity from callbacks. A later-discovered Host session-rollover guard now retains the first new-session event in the spool and exits with an explicit restart-required status instead of consuming it through an old-session OMS mapper.

ORDER/DEAL callbacks and active-query snapshots feed the same persistent evidence journal. Query rows carry an explicit route account type and fingerprint; HUGANGTONG/SHENGANGTONG execution queries are separate from STOCK. Callback/query duplicates are recorded as semantic duplicates without applying a second fill. Production `guojin`, Galaxy and generic Host paths do not activate this sink.

## Changed files
Implementation: `src/bigqmt_autotrader/qmt/{host,guojin_sim_oms,guojin_evidence,commands}.py`, `src/bigqmt_autotrader/oms/{repository,evidence,broker_evidence_v1,db}.py`, migration `0007.sql`, and V05 template/generated deployments. Tests: `tests/qmt/test_guojin_sim_host_oms.py`, mapper/instance/migration tests, `tests/contract/test_qmt_linked_execution_query.py`, and side-effect audit allowlist.

## Tests / formal verification
On 2026-09-21, Python from `D:\gitee\miniQMT\.venv` with repository `src` on `PYTHONPATH`:

- `pytest -q -p no:cacheprovider`: **436 passed** in 71.81 s after the session-rollover regression was added.
- `python tools/audit_side_effect_calls.py`: PASS.
- `python tools/build_qmt_deployments.py --check`: PASS.
- `python tools/verify_bridge_protocol_exhaustive.py`: PASS, 4608 ingress transitions plus spool idempotency/conflict/expiry.
- `python tools/verify_bridge_schema_contract.py`: PASS.
- `python tools/verify_broker_evidence_contract.py`: PASS, 7200 cases.
- `git diff --check`: PASS. No FSM transition changed, so TLC is not triggered.
- `python tools/verify_workflow_contract.py`: **FAIL on pre-existing P6-T002 Architect review frontmatter** (`review_of mismatch`, `task_file mismatch`). The Agent did not alter that Architect-owned file or relax the validator.

## Runtime validation
Market-hours `guojin_sim` only:

1. `511880.SH` BUY 100 @1.00: broker ACK, exact-token cancel, OMS `CANCELLED` with fill 0. Another `511880.SH` BUY 100 @200.00: broker ORDER and DEAL, OMS `FILLED` quantity 100. Host restart preserved both states and did not replay commands.
2. After the user loaded the updated V05, current QMT session `a699da30438c44c3bfe55c4d8a0ab214` emitted an active snapshot with explicit STOCK and HUGANGTONG ORDER/DEAL route fields and zero query errors.
3. `00700.HGT` BUY 100 @1.00, client `p6t003-hgt-20260921-01`, command `2d2142e2d65a42aa9966c547d7a8ddd7`: `SIMULATION_SUBMIT_CALL_RETURNED`, broker order `2`, trade `14423`, ORDER ACK then FULL_FILL and DEAL. Because the previously running Host was still pinned to the prior QMT session, it initially quarantined those callbacks. No retry or second submit was made. After restarting only the `guojin_sim` Host and allowing its old leader lease to expire, deterministic replay ingested ORDER seq 61/62 and DEAL seq 63 (`evidence_ingested=true`, quarantine 0); OMS order became `FILLED`, quantity 100.
4. Read-only `REQUEST_SNAPSHOT` command `5721b3f0c2024c47a0c9323199279b14` produced snapshot seq 95: seven orders/four deals, query errors 0, `evidence_ingested=true`, quarantine 0. The HUGANGTONG active-query rows carried route fingerprint `sha256:e475f1a12b1bede72aafada79c0d876e3549a33985b6ce0d3df6baca9fa6c43d`; OMS recorded them as `SEMANTIC_DUPLICATE`, keeping the fill at 100.
5. At the user's request, additional simulation-only market-hours executions: `00700.HGT SELL 100 @1.00` (broker order `3`, trade `14424`), `00700.SGT BUY 100 @1.00` (order `4`, trade `0600000000011739`), and `00700.SGT SELL 100 @1.00` (order `5`, trade `0600000000011740`). All three produced settled ORDER and DEAL callbacks with `evidence_ingested=true`, OMS `FILLED` quantity 100 each, and semantic quarantine 0. Repeated active snapshots seq 124 and 128 ingested both linked routes with query errors 0 and without double fills.
6. At the user's further request, `204001.SH` GC001 `SELL 10 @1.490` after 15:00 in `guojin_sim` only: command `6ad8e2a9233f4dde8bc548761b9e387b`, broker order `4749`, trade `8100000000051471`. Settled ACK, full-fill ORDER and DEAL all had `evidence_ingested=true`; OMS `FILLED` quantity 10. The initial no-broker-ID callback was quarantined as transient. Active snapshot seq 143 reported eleven orders/eight deals, query errors 0, and evidence ingestion true. GC001 remains forbidden in production live canary.
7. State-path probes: another GC001 `SELL 10 @100.000` also **filled** (broker order `4750`, trade `8100000000051472`), despite being far from the observed 1.49 quote; an exact-token cancel after that terminal fill returned `SIMULATION_CANCEL_NOT_CANCELLABLE`, `live_side_effect=false`, and OMS remained `FILLED`. A `511880.SH BUY 100 @1.00` submitted after the regular equity close was ACKed but unfilled (broker order `4751`); exact-token cancellation returned `SIMULATION_CANCEL_SIGNAL_SENT` and the settled callback moved OMS to `CANCELLED`, fill 0. These are simulation behavior measurements, not evidence that production accepts such prices or after-close equity orders.
8. The updated Host was then restarted after every task test order reached a terminal OMS state and the command inbox was empty. New Host PID `15060` loaded the same validated QMT session, replayed clean snapshot seq 170 (13 orders/nine deals, query errors 0, `evidence_ingested=true`, quarantine 0), and preserved all nine task OMS orders without double fills or command resubmission.

## Mutation accounting
```text
guojin_sim submits = 9 (task total: 3 STOCK ETF, 2 HUGANGTONG, 2 SHENGANGTONG, 2 GC001)
guojin_sim cancels = 3 (task total: 2 settled exact-token cancels, 1 filled-order no-op)
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
UNKNOWN = 0
```

## Quarantine / evidence accounting
Earlier transient/unsettled STOCK callback rows remained quarantined as designed. On the new HGT session, an old-session Host temporarily quarantined three callbacks because it lacked the new durable command identity; restarting the Host against the current manifest and replaying the same records yielded `evidence_ingested=true` for all settled rows and semantic quarantine depth 0. Both linked-account active-query routes produced semantic duplicates, not second fills. Three later initial no-broker-ID callbacks (two GC001, one ETF) raised the current semantic quarantine depth to 3; all corresponding settled callbacks ingested successfully. Unregistered or malformed evidence remains fail-closed.

## Safety declaration
No production authority was broadened. There were **zero** production `guojin`, Galaxy or generic mutations. No UNKNOWN command was blindly retried. The single initial HGT probe filesystem permission failure happened before a command file was written; absence of the command was checked before publishing it once.

## Deviations / blockers
The workflow contract validator fails on `workflow/reviews/P6-T002-I01__architect-review.md` because its pre-existing `review_of` and `task_file` metadata do not match the contract. P6-T003 explicitly forbids Agent edits to Architect review files. Agent -> Architect handoff is withheld until that owner-owned metadata is repaired and the contract passes. The Host currently running for `guojin_sim` is PID 15060, pinned to the current session and running the new rollover guard. The simulator's price and trading-hours behavior should not be used to validate production order policy.

## Handoff
Pending the above Architect-owned workflow contract repair. The Agent will then use `tools/agent_workflow_handoff.py` and set `REVIEW_READY`; no next task or Architect review is created here.
