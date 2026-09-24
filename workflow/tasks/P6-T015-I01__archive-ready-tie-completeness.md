---
workflow_schema: 1
phase: P6
task_id: P6-T015
iteration: I01
task_key: P6-T015-I01
state: AGENT_READY
owner: agent
audit_base_commit: d3c65112aceb2626960749e06cc7174d07d65eed
expected_report: workflow/reports/P6-T015-I01__implementation-report.md
expected_review: workflow/reviews/P6-T015-I01__architect-review.md
---

# Archive bridge_ready same-timestamp tie completeness

## Objective

Close the non-blocking discovery edge found during the independent P6-T014 review:

> when a loose `bridge_ready` and a committed-archive candidate have the same
> `timestamp_ms`, archive pruning must not skip a candidate that could win the
> final `(timestamp_ms, sequence, session_id)` ordering.

The final selected readiness event must be identical to the result obtained by
considering every eligible loose and integrity-valid archived `bridge_ready`
event under the existing tuple ordering.

## Scope

This is a narrow Host discovery hardening task.

Allowed product file:

- `src/bigqmt_autotrader/qmt/instances.py`

Primary regression file:

- `tests/qmt/test_instance_discovery.py`

Do not modify OMS, Risk, mapper, execution bridge, broker evidence semantics,
QMT-side mutation artifacts, production authority, or runtime trading limits.

## Required behavior

The current fast-stop logic uses archive manifest `last_timestamp_ms` to avoid
opening archives that cannot contain a newer readiness event. Preserve that
optimization, but make it tie-complete.

At minimum prove:

1. loose and archived `bridge_ready` share the same `timestamp_ms`;
2. archived event has a higher `sequence` and is therefore selected;
3. the inverse/lower archived sequence does not incorrectly replace the loose event;
4. existing behavior where a strictly newer loose readiness event wins remains intact;
5. corrupt/malformed/mismatched committed archives still fail closed exactly as before.

A minimal fix such as changing the pruning boundary from `<=` to `<` is
acceptable only if the regression tests prove the full ordering invariant and
no integrity check is weakened.

## Safety invariants

- No broker submit/cancel or other external mutation.
- No change to simulation/live-canary authorization.
- No relaxation of archive checkpoint, hash, manifest, trading-day, event-count,
  stream-digest, account-fingerprint, symlink/reparse, or protocol validation.
- Do not treat an invalid archive as ignorable if current behavior is fail-closed.
- Do not broaden discovery to uncommitted archive material.

## Required verification

Run at least:

```bash
pytest -q tests/qmt/test_instance_discovery.py
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/audit_side_effect_calls.py
pytest -q
```

If the full suite has a known baseline/environment failure, record the exact
failure and prove it is unrelated; do not silently downgrade the Gate.

## Exit criteria

- Same-millisecond archive/loose tie is evaluated with the existing final tuple ordering.
- Targeted regressions cover both archived-wins and loose-wins tie cases.
- Existing archive integrity/fail-closed tests remain green.
- Full verification is green or any external baseline blocker is explicitly documented.
- Standard Agent -> Architect handoff is committed and pushed.
