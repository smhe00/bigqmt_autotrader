#!/usr/bin/env python3
"""Verify repository Architect/Agent workflow structure and active handoff consistency."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflow"
TASKS = WORKFLOW / "tasks"
REPORTS = WORKFLOW / "reports"
REVIEWS = WORKFLOW / "reviews"
STATE = WORKFLOW / "control" / "WORKFLOW_STATE.yaml"

KEY_RE = re.compile(r"^P(?P<phase>\d+)-T(?P<task>\d{3})-I(?P<iteration>\d{2})$")
TASK_FILE_RE = re.compile(
    r"^(?P<key>P\d+-T\d{3}-I\d{2})__(?P<slug>[a-z0-9][a-z0-9-]*)\.md$"
)
REPORT_FILE_RE = re.compile(
    r"^(?P<key>P\d+-T\d{3}-I\d{2})__implementation-report\.md$"
)
REVIEW_FILE_RE = re.compile(
    r"^(?P<key>P\d+-T\d{3}-I\d{2})__architect-review\.md$"
)

REPORT_STATUSES = {"AWAITING_AGENT", "REVIEW_READY"}
REVIEW_STATUSES = {
    "AWAITING_REVIEW",
    "PASS",
    "CHANGES_REQUIRED",
    "BLOCKED",
    "USER_ESCALATION",
}

STATE_OWNER = {
    "ARCHITECT_PLANNING": "architect",
    "AGENT_READY": "agent",
    "CHANGES_REQUIRED": "agent",
    "REVIEW_READY": "architect",
    "PASS": "architect",
    "BLOCKED": "architect",
    "USER_ESCALATION": "architect",
}


def fail(messages: list[str]) -> None:
    if messages:
        raise SystemExit("WORKFLOW CONTRACT FAILED\n" + "\n".join(messages))


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path.relative_to(ROOT)} missing YAML-style frontmatter")
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return result
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    raise ValueError(f"{path.relative_to(ROOT)} unterminated frontmatter")


def scalar(text: str, key: str) -> str | None:
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\n#]+))\s*$",
        text,
    )
    if not match:
        return None
    return next((g.strip() for g in match.groups() if g is not None), None)


def list_value(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.fullmatch(rf"{re.escape(key)}:\s*", line):
            result: list[str] = []
            for child in lines[index + 1 :]:
                if child and not child.startswith((" ", "\t")):
                    break
                match = re.match(r"\s+-\s+[\"']?([^\"'#]+)[\"']?\s*$", child)
                if match:
                    result.append(match.group(1).strip())
            return result
    return []


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> None:
    errors: list[str] = []

    for directory in (TASKS, REPORTS, REVIEWS, STATE.parent):
        if not directory.is_dir():
            errors.append(f"missing workflow directory: {rel(directory)}")
    if not STATE.is_file():
        errors.append(f"missing state file: {rel(STATE)}")
    if errors:
        fail(errors)

    task_by_key: dict[str, Path] = {}
    report_by_key: dict[str, Path] = {}
    review_by_key: dict[str, Path] = {}

    for path in sorted(TASKS.glob("*.md")):
        if path.name == "README.md":
            continue
        match = TASK_FILE_RE.fullmatch(path.name)
        if not match:
            errors.append(f"invalid task filename: {rel(path)}")
            continue
        key = match.group("key")
        if key in task_by_key:
            errors.append(f"duplicate task key: {key}")
        task_by_key[key] = path

    for path in sorted(REPORTS.glob("*.md")):
        if path.name == "README.md":
            continue
        match = REPORT_FILE_RE.fullmatch(path.name)
        if not match:
            errors.append(f"invalid report filename: {rel(path)}")
            continue
        key = match.group("key")
        if key in report_by_key:
            errors.append(f"duplicate report key: {key}")
        report_by_key[key] = path

    for path in sorted(REVIEWS.glob("*.md")):
        if path.name == "README.md":
            continue
        match = REVIEW_FILE_RE.fullmatch(path.name)
        if not match:
            errors.append(f"invalid review filename: {rel(path)}")
            continue
        key = match.group("key")
        if key in review_by_key:
            errors.append(f"duplicate review key: {key}")
        review_by_key[key] = path

    task_keys = set(task_by_key)
    report_keys = set(report_by_key)
    review_keys = set(review_by_key)

    for key in sorted(task_keys - report_keys):
        errors.append(f"task has no matched report: {key}")
    for key in sorted(task_keys - review_keys):
        errors.append(f"task has no matched review: {key}")
    for key in sorted(report_keys - task_keys):
        errors.append(f"orphan report: {key}")
    for key in sorted(review_keys - task_keys):
        errors.append(f"orphan review: {key}")

    iterations: dict[tuple[int, int], list[int]] = defaultdict(list)
    for key in sorted(task_keys):
        match = KEY_RE.fullmatch(key)
        if not match:
            errors.append(f"invalid task key syntax: {key}")
            continue
        iterations[(int(match["phase"]), int(match["task"]))].append(
            int(match["iteration"])
        )

        task_path = task_by_key[key]
        report_path = report_by_key.get(key)
        review_path = review_by_key.get(key)
        if report_path is None or review_path is None:
            continue

        try:
            task_meta = frontmatter(task_path)
            report_meta = frontmatter(report_path)
            review_meta = frontmatter(review_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        expected_report = f"workflow/reports/{key}__implementation-report.md"
        expected_review = f"workflow/reviews/{key}__architect-review.md"

        if task_meta.get("task_key") != key:
            errors.append(f"{rel(task_path)} task_key mismatch")
        if task_meta.get("expected_report") != expected_report:
            errors.append(f"{rel(task_path)} expected_report mismatch")
        if task_meta.get("expected_review") != expected_review:
            errors.append(f"{rel(task_path)} expected_review mismatch")

        if report_meta.get("task_key") != key:
            errors.append(f"{rel(report_path)} task_key mismatch")
        if report_meta.get("reply_to") != rel(task_path):
            errors.append(f"{rel(report_path)} reply_to mismatch")
        if report_meta.get("status") not in REPORT_STATUSES:
            errors.append(f"{rel(report_path)} invalid report status")

        if review_meta.get("task_key") != key:
            errors.append(f"{rel(review_path)} task_key mismatch")
        if review_meta.get("review_of") != rel(report_path):
            errors.append(f"{rel(review_path)} review_of mismatch")
        if review_meta.get("task_file") != rel(task_path):
            errors.append(f"{rel(review_path)} task_file mismatch")
        if review_meta.get("status") not in REVIEW_STATUSES:
            errors.append(f"{rel(review_path)} invalid review status")

    for group, values in sorted(iterations.items()):
        ordered = sorted(values)
        expected = list(range(1, max(ordered) + 1))
        if ordered != expected:
            phase, task = group
            errors.append(
                f"P{phase}-T{task:03d} iterations are not contiguous from I01: {ordered}"
            )

    state_text = STATE.read_text(encoding="utf-8")
    current_key = scalar(state_text, "task_key")
    state_name = scalar(state_text, "state")
    owner = scalar(state_text, "owner")
    task_file = scalar(state_text, "task_file")
    report_file = scalar(state_text, "expected_report_file")
    review_file = scalar(state_text, "expected_review_file")
    report_status = scalar(state_text, "report_status")
    review_status = scalar(state_text, "review_status")
    handoff_id = scalar(state_text, "handoff_id")
    authorized_next = list_value(state_text, "authorized_next")

    if current_key not in task_by_key:
        errors.append(f"active task_key missing from tasks: {current_key}")
    else:
        expected_task_path = rel(task_by_key[current_key])
        expected_report_path = rel(report_by_key[current_key])
        expected_review_path = rel(review_by_key[current_key])
        if task_file != expected_task_path:
            errors.append("WORKFLOW_STATE task_file does not match active task_key")
        if report_file != expected_report_path:
            errors.append("WORKFLOW_STATE expected_report_file mismatch")
        if review_file != expected_review_path:
            errors.append("WORKFLOW_STATE expected_review_file mismatch")

        try:
            active_report = frontmatter(report_by_key[current_key])
            active_review = frontmatter(review_by_key[current_key])
            if report_status != active_report.get("status"):
                errors.append("WORKFLOW_STATE report_status differs from report frontmatter")
            if review_status != active_review.get("status"):
                errors.append("WORKFLOW_STATE review_status differs from review frontmatter")
        except ValueError as exc:
            errors.append(str(exc))

    expected_owner = STATE_OWNER.get(state_name or "")
    if expected_owner is None:
        errors.append(f"unknown workflow state: {state_name}")
    elif owner != expected_owner:
        errors.append(
            f"workflow state {state_name} requires owner={expected_owner}, got {owner}"
        )

    if state_name in {"AGENT_READY", "CHANGES_REQUIRED"}:
        if authorized_next != [current_key]:
            errors.append(
                "agent-owned state requires authorized_next to contain exactly current task_key"
            )
        if report_status != "AWAITING_AGENT":
            errors.append("agent-owned state requires report_status=AWAITING_AGENT")
        if review_status != "AWAITING_REVIEW":
            errors.append("agent-owned state requires review_status=AWAITING_REVIEW")
    elif state_name == "REVIEW_READY":
        if authorized_next:
            errors.append("REVIEW_READY must have authorized_next=[]")
        if report_status != "REVIEW_READY":
            errors.append("REVIEW_READY requires report_status=REVIEW_READY")
        if review_status != "AWAITING_REVIEW":
            errors.append("REVIEW_READY requires review_status=AWAITING_REVIEW")
    elif state_name in {
        "ARCHITECT_PLANNING",
        "PASS",
        "BLOCKED",
        "USER_ESCALATION",
    }:
        if authorized_next:
            errors.append(f"{state_name} must have authorized_next=[]")

    if current_key and handoff_id and current_key not in handoff_id:
        errors.append("handoff_id must include current task_key")

    fail(errors)
    print("WORKFLOW CONTRACT PASS")
    print(f"  active: {current_key}")
    print(f"  state: {state_name}")
    print(f"  owner: {owner}")
    print(f"  matched task/report/review sets: {len(task_keys)}")


if __name__ == "__main__":
    main()
