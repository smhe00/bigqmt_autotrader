---
workflow_schema: 1
phase: P6
task_id: P6-T021
iteration: I01
task_key: P6-T021-I01
review_of: workflow/reports/P6-T021-I01__implementation-report.md
task_file: workflow/tasks/P6-T021-I01__fix-preflight-command-frame-fuse.md
status: PASS
owner: architect
---

# P6-T021-I01 Architect Review

## 1. Gate verdict

`PASS`

## 2. Reviewed commits

- Task base: `cd030e6a2e02c5c7efef0a35fc03d4932c5c2ea0`
- Task activation: `1a14842`
- Agent implementation: `1ff02a9e071db2549a7e20777f98dbdf7e170273`
- Agent handoff / review head: `394dc6ded0fde595ed09838e29c6f3aa4baf0137`

## 3. Independent code audit

The reported blocker was real: the old preflight read mutation fields from a flat JSON
object while the durable command protocol stores them in an authenticated/validated nested
command frame. A real published SUBMIT_LIMIT/CANCEL_ORDER could therefore be missed and the
session fuse incorrectly reported unused.

The fix is narrow and correct:

- it imports and uses the production `decode_command_frame()` and shared
  `MAX_COMMAND_FRAME_BYTES` rather than introducing a second parser or size contract;
- it reads the validated `QmtCommand.command_type` and
  `payload["expected_qmt_session_id"]`;
- it examines every regular entry in `commands/inbox`, `claimed`, `processed` and
  `unknown`, independent of filename extension;
- a current-session submit/cancel consumes the fuse; a foreign-session command does not;
- unreadable, oversized, malformed, contract-invalid and unattributable mutation frames
  produce NO-GO rather than being treated as unused;
- non-mutation snapshot commands do not consume the fuse;
- `rejected/` remains excluded exactly as the task requires because the bridge rejected
  those commands before broker mutation.

No broker execution path, authority pin, fuse value, schema, frozen Core or QMT deployment
artifact changed. The static side-effect surface remains unchanged.

The regression fixtures use `QmtCommandSpool.publish_submit()`, `publish_cancel()` and
`publish_snapshot_request()`, then move immutable frames between durable states. This
matches the production frame layout and directly prevents restoration of the flat-JSON bug.

## 4. Verification audit

Independent local verification on review head:

- `pytest tests/qmt/test_live_canary_runtime_preflight.py -q`: `24 passed in 2.51s`;
- `pytest -q`: `649 passed in 143.88s`;
- workflow contract: PASS;
- Core/Runtime dependency boundary: PASS;
- Core v1 release Gate: PASS;
- Bridge protocol finite conformance: PASS (`4608` event transitions plus command spool
  idempotency/conflict/expiry);
- standalone QMT deployment check: PASS;
- broker side-effect surface audit: PASS.

The first local invocation could not obtain a writable system temporary directory in the
new environment. Re-running with a repository-scoped temporary directory passed; that
environment condition is unrelated to the candidate and the temporary directory was removed.

## 5. Findings

NONE.

The task document contains two Markdown hard-break trailing spaces, but they predate the
implementation and are presentation syntax, not a product or Gate defect.

## 6. Gate decision

`PASS`.

The preflight now detects real durable command frames and fails closed whenever the live
canary fuse state cannot be established. It is safe to close P6-T021 without authorizing or
executing a canary.

## 7. Next handoff

Stop at PASS. Do not activate P6-T022 from this review; that separate audit-base task requires
an explicit workflow activation.
