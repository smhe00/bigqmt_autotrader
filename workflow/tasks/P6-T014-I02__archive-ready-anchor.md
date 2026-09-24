---
workflow_schema: 1
phase: P6
task_id: P6-T014
iteration: I02
task_key: P6-T014-I02
state: CHANGES_REQUIRED
owner: agent
audit_base_commit: 570a7f3bd111ba166340e10c1f57e910aeeb4f55
expected_report: workflow/reports/P6-T014-I02__implementation-report.md
expected_review: workflow/reviews/P6-T014-I02__architect-review.md
---

# Archive-aware bridge readiness and SGT runtime retry

## Objective

Repair Host instance discovery so a coherent, still-active QMT session remains
valid after daily archival moves its only `bridge_ready` frame out of
`inbox/processed`.  Preserve all existing fail-closed identity and capability
checks, then resume the P6-T014 SGT Core runtime gate if preflight becomes safe.

## Scope

Product-code scope is limited to:

- `src/bigqmt_autotrader/qmt/instances.py`;
- focused instance/archive tests under `tests/qmt/`;
- this iteration's workflow report and control state.

The readiness lookup may use a committed daily archive only when its manifest
and gzip payload agree on identity and integrity.  It must select the globally
latest valid `bridge_ready` across loose and archived evidence, reject corrupt
or mismatched archive pairs, and avoid trusting archive filenames or manifest
session summaries as substitutes for the decoded event.

After implementation and tests, start Host against the unchanged active
`guojin_sim` session.  If backlog replay survives and all original I01
preconditions pass, continue the original single-submit `.SGT` runtime scenario.
If market/tick/route/session evidence is stale or ambiguous, stop without
mutation and report the exact gate.

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T014-I02__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T014-I02__architect-review.md

## Safety boundaries

- No weakening of manifest, protocol, terminal instance, session, account,
  build, execution-mode or mutation-capability validation.
- No fallback to an unverified/corrupt/partial archive.
- `guojin_sim` submit <= 1 and cleanup cancel <= 1 only after full preflight.
- Production Guojin/Galaxy/generic mutation = 0.
- No blind retry after UNKNOWN or ambiguous broker crossing.
- Do not modify bridge mutation authority, Risk, mapper, OMS lifecycle rules or
  archive deletion policy in this iteration.

## Required verification

Add regression coverage for at least:

1. current-session readiness found only in a valid archive;
2. a newer loose readiness event still wins;
3. corrupt gzip, digest mismatch, malformed frame and manifest/archive mismatch
   fail closed or are excluded without accepting a stale session;
4. prior instance discovery safety cases remain green.

Run:

```bash
pytest -q tests/qmt/test_instance_discovery.py tests/qmt/test_spool_archive.py
pytest -q
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/audit_side_effect_calls.py
```

## Exit criteria

- Host validates the unchanged active `guojin_sim` session after archival,
  without requiring a V05 restart.
- Backlog replay completes while the repaired leader heartbeat remains valid.
- Archive corruption or identity ambiguity remains fail-closed in tests.
- Full CI and all required gates pass.
- If runtime prerequisites remain current, the original SGT exact-fill evidence
  is completed; otherwise zero mutation and the precise environmental gate are
  recorded.
- Standard Agent -> Architect handoff is committed and pushed.
