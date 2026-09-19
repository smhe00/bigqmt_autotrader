#!/usr/bin/env python3
"""Create and activate the next matched workflow task/report/review trio."""

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


def frontmatter_scalar(path: Path, key: str) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SystemExit(f"{path.relative_to(ROOT)} missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise SystemExit(f"{path.relative_to(ROOT)} unterminated frontmatter")
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text[:end])
    if not match:
        raise SystemExit(f"{path.relative_to(ROOT)} missing frontmatter field {key}")
    return match.group(1).strip().strip('"').strip("'")


def replace_scalar(text: str, key: str, value: str, *, quote: bool = True) -> str:
    rendered = f'"{value}"' if quote else value
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*.*$")
    if len(pattern.findall(text)) != 1:
        raise SystemExit(f"expected exactly one {key} in WORKFLOW_STATE")
    return pattern.sub(f"{key}: {rendered}", text, count=1)


def replace_authorized_next(text: str, task_key: str) -> str:
    inline = re.compile(r"(?m)^authorized_next:\s*\[\s*\]\s*$")
    block = re.compile(r"(?m)^authorized_next:\s*$\n(?:^[ \t]+-[^\n]*\n)*")
    replacement = f'authorized_next:\n  - "{task_key}"\n'
    if inline.search(text):
        return inline.sub(replacement.rstrip("\n"), text, count=1)
    if len(block.findall(text)) == 1:
        return block.sub(replacement, text, count=1)
    raise SystemExit("expected one authorized_next field")


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
        description="Create and activate task/report/review files with one deterministic task_key."
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
    owner = scalar(state_text, "owner")
    review_rel = scalar(state_text, "expected_review_file")
    handoff_seq = int(scalar(state_text, "handoff_seq"))

    if current_state != "ARCHITECT_PLANNING" or owner != "architect":
        raise SystemExit(
            f"scaffolding requires ARCHITECT_PLANNING/architect, got {current_state}/{owner}"
        )

    current_review = ROOT / review_rel
    if not current_review.is_file():
        raise SystemExit(f"current review missing: {review_rel}")
    current_verdict = frontmatter_scalar(current_review, "status")

    requested_mode = "next-task" if args.next_task else "next-iteration"
    expected_verdict = "PASS" if requested_mode == "next-task" else "CHANGES_REQUIRED"
    if current_verdict != expected_verdict:
        raise SystemExit(
            f"{requested_mode} requires current review verdict={expected_verdict}, "
            f"got {current_verdict}"
        )

    key, task_id, iteration = next_key(current_key, requested_mode)
    phase = key.split("-", 1)[0]
    active_state = "AGENT_READY" if requested_mode == "next-task" else "CHANGES_REQUIRED"

    task_path = TASKS / f"{key}__{args.slug}.md"
    report_path = REPORTS / f"{key}__implementation-report.md"
    review_path = REVIEWS / f"{key}__architect-review.md"

    task_rel = task_path.relative_to(ROOT).as_posix()
    report_rel = report_path.relative_to(ROOT).as_posix()
    review_rel_new = review_path.relative_to(ROOT).as_posix()

    task = f"""---
workflow_schema: 1
phase: {phase}
task_id: {task_id}
iteration: {iteration}
task_key: {key}
state: {active_state}
owner: agent
audit_base_commit: {args.audit_base_commit}
expected_report: {report_rel}
expected_review: {review_rel_new}
---

# {args.title}

## Objective

Architect: fill the exact implementation objective.

## Scope

Architect: fill allowed files and required changes.

## Workflow communication files

Agent may always update:

- {report_rel}
- workflow/control/WORKFLOW_STATE.yaml

Agent must not modify:

- {review_rel_new}

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
review_target: {review_rel_new}
---

# {key} Implementation Report

## 1. Result

- Status: AWAITING_AGENT
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

Agent: fill, or NONE.

## 7. Handoff to Architect

After filling this report, run:

python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>

Then run:

python tools/verify_workflow_contract.py

Commit the report and WORKFLOW_STATE changes together. Do not modify the Architect review
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

AWAITING_REVIEW

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

After completing the review body, run tools/architect_workflow_verdict.py.
"""

    write_new(task_path, task)
    write_new(report_path, report)
    write_new(review_path, review)

    new_seq = handoff_seq + 1
    handoff_id = f"{key}-architect-to-agent-{new_seq:04d}"
    state_text = replace_scalar(state_text, "handoff_seq", str(new_seq), quote=False)
    state_text = replace_scalar(state_text, "handoff_id", handoff_id)
    state_text = replace_scalar(state_text, "phase", phase)
    state_text = replace_scalar(state_text, "task_id", task_id)
    state_text = replace_scalar(state_text, "iteration", iteration)
    state_text = replace_scalar(state_text, "task_key", key)
    state_text = replace_scalar(state_text, "state", active_state)
    state_text = replace_scalar(state_text, "owner", "agent")
    state_text = replace_scalar(state_text, "audit_base_commit", args.audit_base_commit)
    state_text = replace_scalar(state_text, "task_file", task_rel)
    state_text = replace_scalar(state_text, "expected_report_file", report_rel)
    state_text = replace_scalar(state_text, "expected_review_file", review_rel_new)
    state_text = replace_scalar(state_text, "report_status", "AWAITING_AGENT")
    state_text = replace_scalar(state_text, "review_status", "AWAITING_REVIEW")
    state_text = replace_authorized_next(state_text, key)
    STATE.write_text(state_text, encoding="utf-8", newline="\n")

    print("WORKFLOW HANDOFF ACTIVATED")
    print(f"  task_key: {key}")
    print(f"  state: {active_state}")
    print("  owner: agent")
    print(f"  task: {task_rel}")
    print(f"  report: {report_rel}")
    print(f"  review: {review_rel_new}")
    print(f"  handoff_id: {handoff_id}")
    print()
    print("Run: python tools/verify_workflow_contract.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
