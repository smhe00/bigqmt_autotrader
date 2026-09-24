---
workflow_schema: 1
phase: P6
task_id: P6-T016
iteration: I01
task_key: P6-T016-I01
state: AGENT_READY
owner: agent
audit_base_commit: 2199c1e25c9bde474a0636526ce8b9de4451ee95
expected_report: workflow/reports/P6-T016-I01__implementation-report.md
expected_review: workflow/reviews/P6-T016-I01__architect-review.md
---

# Development environment migration documentation and repository cleanup

## Objective

Make the repository self-contained for migration to a new Windows development
environment. Reconcile every living overview/status document with the frozen
Core v1 contract and the completed P6 runtime gates, add a reproducible migration
runbook, classify immutable historical evidence, and remove only disposable local
build/test artifacts.

## Scope

Allowed tracked files:

- `README.md`;
- living documents under `docs/`;
- a new `docs/README.md` document index;
- this task and its implementation report;
- `.gitignore` only if cleanup reveals a missing disposable-artifact pattern.

Historical dated Gate/audit documents and all prior workflow task/report/review
files are immutable evidence and must not be rewritten or deleted. Product code,
schemas, formal models, frozen Core contracts and QMT deployment files are out of
scope.

Disposable ignored artifacts may be removed only after resolving their absolute
paths under the repository root. User-owned untracked `deck/` files are out of scope.

## Workflow communication files

Agent may always update:

- workflow/reports/P6-T016-I01__implementation-report.md
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- workflow/reviews/P6-T016-I01__architect-review.md

## Safety boundaries

- No QMT command, broker submit/cancel, account query, runtime restart or other
  trading-side effect.
- Do not weaken or broaden any simulation, LIVE_CANARY or production authority.
- Do not delete audit history, durable runtime data, databases, spool data,
  secrets, user-authored untracked files, or the pinned Core v1 contracts.
- Documentation must distinguish frozen contract, current runtime capability,
  historical evidence and future work.

## Required verification

Run at least:

```text
pytest -q tests/unit/test_documentation_consistency.py
python tools/verify_workflow_contract.py
python tools/verify_core_dependency_boundary.py
python tools/verify_core_v1_release.py
python tools/audit_side_effect_calls.py
python tools/build_qmt_deployments.py --check
pytest -q
```

Also validate all relative Markdown links in tracked Markdown files.

## Exit criteria

- A fresh developer can clone, create a Python 3.12 environment, run all gates,
  deploy the correct QMT-side artifact and restore only approved runtime state.
- Living documents consistently identify `core-v1.0.0` as frozen and name the
  current Guojin simulation/live-canary builds.
- Historical evidence is indexed as historical rather than silently rewritten.
- Only proven disposable artifacts are removed; `deck/` remains untouched.
- Required verification passes and the result is committed and pushed.
