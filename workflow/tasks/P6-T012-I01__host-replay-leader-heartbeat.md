---
workflow_schema: 1
phase: P6
task_id: P6-T012
iteration: I01
task_key: P6-T012-I01
state: AGENT_READY
owner: agent
audit_base_commit: b190904e6bfdf383c975a635360198e33b529c8c
expected_report: workflow/reports/P6-T012-I01__implementation-report.md
expected_review: workflow/reviews/P6-T012-I01__architect-review.md
---

# P6-T012-I01 — Renew OMS Leader Lease During Long Host Replay

## Objective

Fix exactly one defect:

> Host startup replay must provide periodic OMS leader maintenance so a valid
> `guojin_sim` leader lease cannot expire merely because replaying a large
> historical spool takes longer than the 30-second lease.

This task does not execute broker mutation and does not change trading authority.

## Confirmed defect

Current startup sequence calls
`FileSpoolReceiver.replay_processed_from_latest_clean_snapshot()` before the
normal Host loop begins.

The replay callback currently performs session validation and identity refresh,
but no `oms_runtime.maintain()`. The normal loop heartbeat therefore starts too
late for a long replay.

## Required design

Preserve the existing lease model:

- lease remains 30 seconds;
- heartbeat threshold remains 10 seconds unless a test proves a smaller local
  refactor is necessary;
- an already-expired lease must NOT be resurrected;
- fencing/session checks remain unchanged;
- no background thread is required;
- no broker mutation is allowed.

Preferred repair:

- make each replay/live event boundary provide an OMS maintenance opportunity
  before lease-protected identity/evidence work;
- reuse the same event-boundary helper for replay and normal polling rather than
  special-casing only startup.

Do not increase the lease timeout to hide the bug.

## Allowed implementation scope

Prefer only:

- `src/bigqmt_autotrader/qmt/host.py`
- `tests/qmt/test_guojin_sim_host_oms.py`

Touch `guojin_sim_oms.py` only if strictly necessary and explain why.

Do not modify:

- OMS leader/fencing semantics;
- Core/Runtime boundary;
- Risk;
- broker evidence mapper semantics;
- QMT bridge mutation semantics;
- production authority.

## Required deterministic tests

Do not add a 30-second wall-clock test.

Add deterministic coverage proving at least:

1. processed-spool replay invokes OMS maintenance repeatedly while replay events
   are consumed;
2. a replay longer than one heartbeat interval can renew before the fixed lease
   expires;
3. session rollover still stops before processing an event under a stale mapper;
4. heartbeat failure / lost lease remains fail-closed;
5. no submit/cancel command is emitted by these tests.

Use a fake/injected monotonic clock or a narrow event-boundary helper as needed.

## Verification

Run:

```bash
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/audit_side_effect_calls.py
pytest -q tests/qmt/test_guojin_sim_host_oms.py
pytest -q
```

Full suite must be green on the Agent platform except the already separately
tracked Windows backup/fsync defect; report it distinctly if it remains.

## PASS criteria

- long replay cannot lose a healthy lease merely due to lack of heartbeat;
- no lease resurrection semantics are weakened;
- session rollover behavior remains fail-closed;
- zero broker mutation;
- production/Galaxy/generic authority unchanged;
- targeted tests pass.

## Deferred independent defect

Do not fix `operations/backup.py` in this task. The Windows backup/fsync issue
will receive its own task after P6-T012.
