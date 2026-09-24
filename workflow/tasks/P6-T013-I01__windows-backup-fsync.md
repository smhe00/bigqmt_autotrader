---
workflow_schema: 1
phase: P6
task_id: P6-T013
iteration: I01
task_key: P6-T013-I01
state: AGENT_READY
owner: agent
audit_base_commit: 0b5e111f7b1f77f08445cbdf8c0d8e394e60cd96
expected_report: workflow/reports/P6-T013-I01__implementation-report.md
expected_review: workflow/reviews/P6-T013-I01__architect-review.md
---

# Make SQLite Backup Durability Portable on Windows

## Objective

Fix exactly one defect:

> `create_database_backup()` must create and verify an atomic SQLite backup on
> Windows without calling `os.fsync()` on an incompatible read-only file or
> directory descriptor, while preserving the existing POSIX durability path.

The confirmed Windows failure is:

```text
operations/backup.py:115
with temporary.open("rb") as handle:
    os.fsync(handle.fileno())
OSError: [Errno 9] Bad file descriptor
```

After the file sync is corrected, ordinary POSIX-style directory descriptors
must also not be assumed to work on Windows.

## Scope

Preferred product scope:

- `src/bigqmt_autotrader/operations/backup.py`
- `tests/operations/test_backup.py`

Touch alert backup/restore tests only if a narrowly relevant assertion is
required. Do not modify QMT, OMS, Risk, Core, bridge or trading code.

Required behavior:

1. keep SQLite online backup and integrity/schema verification before publish;
2. close the SQLite target before syncing/publishing the file;
3. sync the temporary backup through a descriptor mode supported by Windows;
4. atomically publish with `os.replace()` only after successful verification
   and file sync;
5. sync parent-directory metadata on platforms that support directory fsync;
6. handle Windows' lack of ordinary directory-fd fsync explicitly rather than
   accidentally weakening or crashing the file-sync path;
7. retain fail-closed cleanup of the temporary file on every pre-publish error;
8. never overwrite an existing destination.

Do not simply remove all fsync calls or suppress arbitrary `OSError` values.
Platform handling must be explicit and unit tested.

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T013-I01__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T013-I01__architect-review.md

## Safety boundaries

- Backup only; no broker, QMT, command spool or account access.
- No trading authority or execution behavior changes.
- Corrupt backup, wrong schema, failed file sync and failed atomic replace remain
  hard errors.
- Existing destination content must remain untouched.
- The known P6-T012 Host heartbeat repair must remain unchanged.

## Required verification

Add deterministic coverage for:

1. successful backup on the Agent's Windows platform;
2. temporary file is opened/synced in a Windows-compatible manner;
3. file-sync failure prevents publish and removes the temporary file;
4. atomic-replace failure preserves failure and cleans temporary state;
5. directory sync is attempted on POSIX and explicitly bypassed or implemented
   through a supported Windows path;
6. existing-destination and corrupt/wrong-schema fail-closed behavior remains;
7. alert journal backup/restore tests pass.

Run:

```bash
pytest -q tests/operations/test_backup.py tests/operations/test_alert_persistence_migration.py
pytest -q
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/audit_side_effect_calls.py
```

## Exit criteria

- All backup and alert backup/restore tests pass on Windows.
- Full Python suite is green; the previous four known failures are eliminated.
- Backup publication remains verified, fail-closed and atomic.
- POSIX directory durability is retained.
- No unrelated product file or trading authority changes.
- Standard Agent -> Architect handoff is committed and pushed to `main`.
