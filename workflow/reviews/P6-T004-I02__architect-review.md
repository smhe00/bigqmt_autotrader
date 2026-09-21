---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I02
task_key: P6-T004-I02
review_of: workflow/reports/P6-T004-I02__implementation-report.md
task_file: workflow/tasks/P6-T004-I02__close-pre-dispatch-crash-windows.md
status: CHANGES_REQUIRED
owner: architect
---

# P6-T004-I02 Architect Review

## Gate verdict

**CHANGES_REQUIRED**

## Reviewed range

- Architect task base: `2b2acd6a0453d1a597fae63aceebe2b80cc6e9d2`
- Final implementation: `56089e69a0a694332ad7d420b8f3f56874a776c4`
- Agent handoff: `e5f814895b500739b5f40ad172d5c4d296d05f39`

Both implementation and handoff GitHub Actions are green. The blocking finding below is a code
review issue not covered by the current single-command restart tests.

## Blocking finding — candidate frame validation uses the wrong `raw`

`GuojinSimOmsRuntime.refresh_identities()` first scans every processed/unknown submit command,
building a list of candidate dictionaries. It then performs a second validation pass.

In that second pass, for an existing OMS intent backed by `qmt_execution_dispatches`, the code
checks:

```python
bytes(dispatch["frame_blob"]) != raw
```

But `raw` is not stored per candidate. It is the local variable left behind by the preceding
filesystem scan loop and therefore contains the bytes of the **last scanned command file**.

Consequences:

- one processed/unknown command: tests pass;
- two or more OMS-owned processed/unknown commands: every earlier candidate is compared against the
  final command's frame and can be falsely rejected as
  `QmtDurableIdentityConflict("OMS order exists without matching durable dispatch authority")`;
- Host restart can fail exactly when the durable history contains multiple normal orders.

This is a restart correctness blocker for the simulation closed loop.

## Required fix

Bind immutable raw frame bytes to each candidate during collection (or equivalently re-read the
candidate's own exact path) and compare each dispatch row against that candidate's own bytes/digest.

Do not weaken the exact authority check.

Add a regression with at least two OMS-owned historical submit commands, preferably covering
different terminal command states such as processed + unknown, and prove restart:

- validates each candidate against its own dispatch frame;
- links/retains both durable identities;
- restores mapper identities for both;
- publishes zero duplicate commands;
- does not create duplicate OMS intents/orders.

Keep all I02 atomicity/expiry/orphan fixes unchanged.

## Decision

Keep task `P6-T004`; create iteration `I03`.

No production authority is granted.
