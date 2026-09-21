---
workflow_schema: 1
phase: P6
task_id: P6-T004
iteration: I03
task_key: P6-T004-I03
reply_to: workflow/tasks/P6-T004-I03__multi-command-restart-identity.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T004-I03__architect-review.md
---

# P6-T004-I03 Implementation Report

## Result

- Status: `REVIEW_READY`
- Architect fix request base: `35f24854bf5055e198ac8d444725ba5bac3e3cf4`
- Implementation commit: `fa7b21542048d0f85c614cae44be8f04842e321e`
- Workflow route repair: `a507627180f3a1e5ea45904699688327001f1875`
- Small-batch policy commit: `54dae74affe034a39507f817e0c875a92154619b`
- Verified CI run: `35602379998` — **SUCCESS**

## Frame-binding fix

The I02 blocker was confirmed: `refresh_identities()` collected multiple processed/unknown
commands, then its second validation pass compared every earlier candidate against the scan loop's
last `raw` frame.

I03 binds immutable frame bytes to the exact candidate:

```python
raw_by_command[command.command_id] = raw
...
bytes(dispatch["frame_blob"]) != raw_by_command[candidate["command_id"]]
```

The exact dispatch-authority check remains unchanged in strength:

- command ID;
- account fingerprint;
- client order ID;
- QMT session;
- broker token;
- command type;
- frame digest;
- exact frame bytes.

No metadata-only fallback was introduced.

## Multi-command restart regression

Added regression coverage with two Host-owned historical submits in one instance/session:

```text
command A -> processed
command B -> unknown
```

Restart now verifies:

- both candidates validate against their own immutable frame;
- both durable QMT identities exist exactly once;
- both OMS intents exist exactly once;
- both mapper identities restore correctly;
- command spool contents are unchanged across restart;
- zero duplicate command publication occurs.

A separate deliberately corrupted dispatch-frame case proves exact mismatch still fails closed.

## Scope

I03 stayed within the scope lock:

- fixed only per-candidate raw-frame binding;
- added multi-command restart regression;
- added deliberate mismatch fail-closed regression;
- no OMS/QMT authority change;
- no runtime broker feature;
- no production LIVE_CANARY change.

The separate workflow small-batch policy commit changes only collaboration scope rules.

## Verification

GitHub Actions run `35602379998`, head
`54dae74affe034a39507f817e0c875a92154619b`:

```text
pytest -q                                      PASS — 453 passed
Verify workflow handoff contract               PASS
Audit broker side-effect call surface          PASS
Verify standalone QMT deployment files         PASS
TLC - Guojin simulation dispatch recovery      PASS
formal-verification job                        PASS
test job                                       PASS
```

The complete permanent formal-verification job finished successfully.

## Safety

```text
guojin_sim broker mutation during I03 = 0
production guojin mutation = 0
galaxy mutation = 0
generic mutation = 0
production LIVE_CANARY authority change = 0
```

## Handoff

The multi-command restart identity blocker is fixed and ready for Architect review.
