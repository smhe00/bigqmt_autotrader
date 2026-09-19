#!/usr/bin/env python3
"""Atomically prepare the Agent -> Architect workflow handoff in the working tree."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow" / "control" / "WORKFLOW_STATE.yaml"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def scalar(text: str, key: str) -> str:
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\n#]+))\s*$",
        text,
    )
    if not match:
        raise SystemExit(f"missing {key} in {STATE.relative_to(ROOT)}")
    return next(g.strip() for g in match.groups() if g is not None)


def replace_scalar(text: str, key: str, value: str, *, quote: bool = True) -> str:
    rendered = f'"{value}"' if quote else value
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*.*$")
    if len(pattern.findall(text)) != 1:
        raise SystemExit(f"expected exactly one {key} in {STATE.relative_to(ROOT)}")
    return pattern.sub(f"{key}: {rendered}", text, count=1)


def replace_frontmatter_scalar(text: str, key: str, value: str) -> str:
    if not text.startswith("---\n"):
        raise SystemExit("report missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise SystemExit("report has unterminated frontmatter")
    head = text[:end]
    tail = text[end:]
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*.*$")
    if len(pattern.findall(head)) != 1:
        raise SystemExit(f"expected exactly one report frontmatter {key}")
    head = pattern.sub(f"{key}: {value}", head, count=1)
    return head + tail


def replace_authorized_next_empty(text: str) -> str:
    block = re.compile(r"(?m)^authorized_next:\s*$\n(?:^[ \t]+-[^\n]*\n)*")
    if len(block.findall(text)) != 1:
        if re.search(r"(?m)^authorized_next:\s*\[\s*\]\s*$", text):
            return text
        raise SystemExit("expected one block-form authorized_next in WORKFLOW_STATE")
    return block.sub("authorized_next: []\n", text, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update the active report and WORKFLOW_STATE together for Agent -> Architect handoff."
    )
    parser.add_argument("--implementation-commit", required=True)
    args = parser.parse_args()

    if not SHA_RE.fullmatch(args.implementation_commit):
        raise SystemExit("--implementation-commit must be a full lowercase 40-hex SHA")

    state_text = STATE.read_text(encoding="utf-8")
    task_key = scalar(state_text, "task_key")
    state_name = scalar(state_text, "state")
    owner = scalar(state_text, "owner")
    report_rel = scalar(state_text, "expected_report_file")
    report_status = scalar(state_text, "report_status")
    review_status = scalar(state_text, "review_status")
    handoff_seq = int(scalar(state_text, "handoff_seq"))

    if state_name not in {"AGENT_READY", "CHANGES_REQUIRED"} or owner != "agent":
        raise SystemExit(
            f"active workflow is not Agent-owned: state={state_name} owner={owner}"
        )
    if report_status != "AWAITING_AGENT":
        raise SystemExit(f"expected report_status=AWAITING_AGENT, got {report_status}")
    if review_status != "AWAITING_REVIEW":
        raise SystemExit(f"expected review_status=AWAITING_REVIEW, got {review_status}")

    report_path = ROOT / report_rel
    if not report_path.is_file():
        raise SystemExit(f"active report missing: {report_rel}")

    report_text = report_path.read_text(encoding="utf-8")
    report_text = replace_frontmatter_scalar(report_text, "status", "REVIEW_READY")
    report_text = re.sub(
        r"(?m)^- Status:\s*\x60AWAITING_AGENT\x60\s*$",
        "- Status: " + chr(96) + "REVIEW_READY" + chr(96),
        report_text,
        count=1,
    )
    report_text = re.sub(
        r"(?m)^- Implementation commit:\s*.*$",
        f"- Implementation commit: {args.implementation_commit}",
        report_text,
        count=1,
    )
    report_text = re.sub(
        r"(?m)^- Final commit:\s*.*$",
        f"- Final commit: {args.implementation_commit}",
        report_text,
        count=1,
    )

    new_seq = handoff_seq + 1
    new_handoff_id = f"{task_key}-agent-to-architect-{new_seq:04d}"
    state_text = replace_scalar(state_text, "handoff_seq", str(new_seq), quote=False)
    state_text = replace_scalar(state_text, "handoff_id", new_handoff_id)
    state_text = replace_scalar(state_text, "state", "REVIEW_READY")
    state_text = replace_scalar(state_text, "owner", "architect")
    state_text = replace_scalar(state_text, "report_status", "REVIEW_READY")
    state_text = replace_scalar(state_text, "review_status", "AWAITING_REVIEW")
    state_text = replace_authorized_next_empty(state_text)

    report_path.write_text(report_text, encoding="utf-8", newline="\n")
    STATE.write_text(state_text, encoding="utf-8", newline="\n")

    print("AGENT HANDOFF PREPARED")
    print(f"  task_key: {task_key}")
    print(f"  report: {report_rel}")
    print("  state: REVIEW_READY")
    print("  owner: architect")
    print(f"  handoff_id: {new_handoff_id}")
    print()
    print("Run: python tools/verify_workflow_contract.py")
    print("Then commit the report + WORKFLOW_STATE changes together.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
