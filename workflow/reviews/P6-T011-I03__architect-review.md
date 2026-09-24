---
workflow_schema: 1
phase: P6
task_id: P6-T011
iteration: I03
task_key: P6-T011-I03
review_of: workflow/reports/P6-T011-I03__implementation-report.md
task_file: workflow/tasks/P6-T011-I03__sgt-linked-fill-core-api.md
status: CHANGES_REQUIRED
owner: architect
---

# P6-T011-I03 Architect Review

## 1. Gate verdict

`CHANGES_REQUIRED`

The SGT fill invariant was not executed. The Agent stopped before mutation after
discovering two independent defects. This is the correct fail-closed behavior.

## 2. Reviewed commits

- Task base: `114ee09ebb7702cdad72ebb16308e44d4a197e5c`
- Workflow retarget commit: `371df9ec196655e7c0836cc0ed89ffa863ab0005`
- Agent handoff head: `b190904e6bfdf383c975a635360198e33b529c8c`
- Runtime implementation diff: none; only workflow/report files changed.

## 3. Independent audit — Host leader lease defect

CONFIRMED.

Current Host startup performs:

```text
build GuojinSimOmsRuntime
 -> acquire 30 s OMS leader lease
 -> replay_processed_from_latest_clean_snapshot()
 -> only after replay enter main loop
 -> oms_runtime.maintain()
```

During replay, FileSpoolReceiver invokes Host `on_event` once per historical
event. That callback currently checks session and calls
`oms_runtime.refresh_identities()`, but it does not call
`oms_runtime.maintain()`.

`GuojinSimOmsRuntime.maintain()` is the mechanism that renews the leader lease
when 10 seconds have elapsed. Therefore a sufficiently long initial replay can
run past the fixed 30-second lease before the main loop gets its first heartbeat.
The next lease-protected write/heartbeat then correctly fails closed with
`OmsLeaderLost: expired OMS leader lease cannot be resurrected`.

The reported 1,792-event replay is fully consistent with this code path.

## 4. Independent audit — Windows backup durability defect

CONFIRMED and independent.

`operations/backup.py` currently performs:

```python
with temporary.open("rb") as handle:
    os.fsync(handle.fileno())
```

On Windows, fsync on that read-only descriptor can raise
`OSError: [Errno 9] Bad file descriptor`. The subsequent parent-directory fsync
also assumes POSIX directory-fd semantics.

This is a real cross-platform durability defect, but it is not the same invariant
as Host replay/leader renewal and must be fixed in a separate task.

## 5. Runtime / safety audit

- guojin_sim submit = 0
- guojin_sim cancel = 0
- production Guojin mutation = 0
- Galaxy mutation = 0
- generic mutation = 0
- no blind retry
- no new UNKNOWN / MANUAL_REVIEW caused by I03
- command inbox empty at handoff

The pre-mutation stop is accepted as safe behavior.

## 6. Gate decision

`CHANGES_REQUIRED`

P6-T011 is not failed as a trading invariant; it remains untested because
prerequisite runtime defects were discovered.

## 7. Next work

Activate one narrow task first:

`P6-T012-I01 — keep OMS leader lease alive during long Host replay`.

After that task passes, fix the independent Windows backup/fsync defect in a
separate task before rescheduling the SGT runtime fill Gate.
