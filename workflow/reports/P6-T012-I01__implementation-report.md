---
workflow_schema: 1
phase: P6
task_id: P6-T012
iteration: I01
task_key: P6-T012-I01
reply_to: workflow/tasks/P6-T012-I01__host-replay-leader-heartbeat.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T012-I01__architect-review.md
---

# P6-T012-I01 Implementation Report

## Result
- Status: `REVIEW_READY`
- Base commit: b190904e6bfdf383c975a635360198e33b529c8c
- Implementation commit: 999ba805192502edbf9cb1990ef4d745572f997b
- Outcome: PASS candidate. Long startup replay now provides an OMS lease
  maintenance opportunity at every event boundary without changing the
  30-second lease, 10-second heartbeat threshold, fencing, or expiry semantics.

## Defect reproduction
The 2026-09-24 runtime preflight reproduced the defect with the unmodified
baseline: Host PID 10116 replayed 1,792 historical events, remained inside
event processing for longer than the 30-second lease, and then raised
`OmsLeaderLost: expired OMS leader lease cannot be resurrected` when control
returned to the normal loop. No broker command was emitted.

The deterministic regression models a 42-second processed-spool replay with a
fake monotonic/UTC clock. Before this repair, the callback had no maintenance
opportunity and the lease would expire before the normal loop. With the repair,
event boundaries at six-second intervals renew at the unchanged ten-second
threshold, and the original lease remains held after the replay.

## Implementation
- `src/bigqmt_autotrader/qmt/host.py`: added
  `_maintain_current_oms_event()`. It first validates that the incoming QMT
  session still matches the mapper-pinned session, then calls
  `runtime.maintain()` and `runtime.refresh_identities()`.
- The existing `on_event` callback now uses that helper. The same callback is
  already used by both `replay_processed_from_latest_clean_snapshot()` and
  normal `poll_once()`, so startup replay and live polling share one boundary.
- Session validation intentionally precedes maintenance: a new-session event
  raises `QmtOmsSessionRollover` before either heartbeat or mapper refresh.
- A lost/expired lease raised by `maintain()` propagates. The spool receiver
  leaves the durable event in inbox and fails closed; no resurrection or retry
  semantics changed.
- `tests/qmt/test_guojin_sim_host_oms.py`: added deterministic coverage for
  per-event replay maintenance, a 42-second replay crossing multiple heartbeat
  intervals, rollover-before-maintenance, lease-loss retention/fail-close, and
  zero command emission.
- `guojin_sim_oms.py`, leader/fencing code, Risk, mapper semantics, bridge
  mutation code, production authority, and `operations/backup.py` were not
  modified.

## Verification
- `pytest -q tests/qmt/test_guojin_sim_host_oms.py`: `23 passed`.
- Full suite: `603 passed, 4 failed`. The only four failures are the explicitly
  deferred Windows backup/fsync defect in `operations/backup.py:115`:
  `OSError: [Errno 9] Bad file descriptor`. They are the same two backup and
  two alert backup/restore failures recorded before this task; no Host/Core/OMS
  regression failed.
- `python tools/verify_workflow_contract.py`: PASS.
- `python tools/verify_core_dependency_boundary.py`: PASS, 39 Core-plane files.
- `python tools/audit_side_effect_calls.py`: PASS; generic/Galaxy mutation
  surface remains zero and no authority widened.
- `git diff --check`: PASS.

## Safety
- simulation submit = 0
- simulation cancel = 0
- production mutation = 0
- No QMT Host or bridge runtime was started by this code-fix task.
- Tests assert that replay, rollover and lost-lease paths create no submit or
  cancel command files.

## Handoff
Ready for standard Agent -> Architect review. Review should confirm event-boundary
maintenance precedes mapper work but follows session fencing, and that the
deferred Windows backup/fsync defect remains outside P6-T012 scope.
