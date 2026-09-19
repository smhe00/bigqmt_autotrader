#!/usr/bin/env python3
"""Create a matched workflow task/report/review trio without guessing filenames."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflow"
TASKS = WORKFLOW / "tasks"
REPORTS = WORKFLOW / "reports"
REVIEWS = WORKFLOW / "reviews"
STATE = WORKFLOW / "control" / "WORKFLOW_STATE.yaml"

KEY_RE = re.compile(r"^P(?P<phase>\d+)-T(?P<task>\d{3})-I(?P<iteration>\d{2})$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def scalar(text: str, key: str) -> str:
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\n#]+))\s*$",
        text,
    )
    if not match:
        raise SystemExit(f"missing {key} in {STATE.relative_to(ROOT)}")
    return next(g.strip() for g in match.groups() if g is not None)


def next_key(current: str, mode: str) -> tuple[str, str, str]:
    match = KEY_RE.fullmatch(current)
    if not match:
        raise SystemExit(f"invalid current task_key: {current}")
    phase = int(match["phase"])
    task = int(match["task"])
    iteration = int(match["iteration"])
    if mode == "next-task":
        task += 1
        iteration = 1
    else:
        iteration += 1
    key = f"P{phase}-T{task:03d}-I{iteration:02d}"
    return key, f"P{phase}-T{task:03d}", f"I{iteration:02d}"


def write_new(path: Path, content: str) -> None:
    if path.exists():
        raise SystemExit(f"refusing to overwrite existing workflow file: {path.relative_to(ROOT)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create task/report/review files sharing one deterministic workflow task_key."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--next-task", action="store_true")
    mode.add_argument("--next-iteration", action="store_true")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--audit-base-commit", required=True)
    args = parser.parse_args()

    if not SLUG_RE.fullmatch(args.slug):
        raise SystemExit("--slug must match [a-z0-9][a-z0-9-]*")
    if not SHA_RE.fullmatch(args.audit_base_commit):
        raise SystemExit("--audit-base-commit must be a full lowercase 40-hex commit SHA")

    state_text = STATE.read_text(encoding="utf-8")
    current_key = scalar(state_text, "task_key")
    current_state = scalar(state_text, "state")

    requested_mode = "next-task" if args.next_task else "next-iteration"
    if requested_mode == "next-task" and current_state not in {
        "PASS",
        "ARCHITECT_PLANNING",
        "BLOCKED",
        "USER_ESCALATION",
    }:
        raise SystemExit(
            f"next task may not be scaffolded from state={current_state}; "
            "finish the current Gate first"
        )
    if requested_mode == "next-iteration" and current_state != "CHANGES_REQUIRED":
        raise SystemExit(
            f"next iteration requires CHANGES_REQUIRED, got state={current_state}"
        )

    key, task_id, iteration = next_key(current_key, requested_mode)
    phase = key.split("-", 1)[0]

    task_path = TASKS / f"{key}__{args.slug}.md"
    report_path = REPORTS / f"{key}__implementation-report.md"
    review_path = REVIEWS / f"{key}__architect-review.md"

    task_rel = task_path.relative_to(ROOT).as_posix()
    report_rel = report_path.relative_to(ROOT).as_posix()
    review_rel = review_path.relative_to(ROOT).as_posix()

    task = f"""---
workflow_schema: 1
phase: {phase}
task_id: {task_id}
iteration: {iteration}
task_key: {key}
state: AGENT_READY
owner: agent
audit_base_commit: {args.audit_base_commit}
expected_report: {report_rel}
expected_review: {review_rel}
---

# {args.title}

## Objective

Architect: fill the exact implementation objective.

## Scope

Architect: fill allowed files and required changes.

## Safety boundaries

Architect: fill explicit prohibited side effects and fail-closed requirements.

## Required verification

Architect: fill mandatory tests and verification commands.

## Exit criteria

Architect: fill objective PASS criteria.
"""

    report = f"""---
workflow_schema: 1
phase: {phase}
task_id: {task_id}
iteration: {iteration}
task_key: {key}
reply_to: {task_rel}
status: AWAITING_AGENT
owner: agent
review_target: {review_rel}
---

# {key} Implementation Report

## 1. Result

- Status: `AWAITING_AGENT`
- Implementation commit:
- Base commit:
- Final commit:

## 2. Files changed

Agent: fill.

## 3. Implementation summary

Agent: fill.

## 4. Verification results

Agent: fill exact commands and results.

## 5. Safety declaration

Agent: explicitly state whether any prohibited side effect occurred.

## 6. Deviations / unresolved items

Agent: fill, or `NONE`.

## 7. Handoff to Architect

When complete, change frontmatter `status` to `REVIEW_READY`, fill final commit SHA,
and do not create the next task.
"""

    review = f"""---
workflow_schema: 1
phase: {phase}
task_id: {task_id}
iteration: {iteration}
task_key: {key}
review_of: {report_rel}
task_file: {task_rel}
status: AWAITING_REVIEW
owner: architect
---

# {key} Architect Review

## 1. Gate verdict

`AWAITING_REVIEW`

## 2. Reviewed commits

- Task base: {args.audit_base_commit}
- Agent implementation commit:
- Review head:

## 3. Independent code audit

Architect: fill.

## 4. Verification audit

Architect: fill.

## 5. Findings

Architect: fill.

## 6. Gate decision

Architect: PASS / CHANGES_REQUIRED / BLOCKED / USER_ESCALATION.

## 7. Next handoff

Architect: record next task key or stop condition.
"""

    write_new(task_path, task)
    write_new(report_path, report)
    write_new(review_path, review)

    print("WORKFLOW TRIO CREATED")
    print(f"  task_key: {key}")
    print(f"  task: {task_rel}")
    print(f"  report: {report_rel}")
    print(f"  review: {review_rel}")
    print()
    print("Next: fill the task body, then explicitly update WORKFLOW_STATE.yaml to activate it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
