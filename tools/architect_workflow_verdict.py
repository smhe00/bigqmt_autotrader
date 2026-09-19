#!/usr/bin/env python3
"""Record an Architect verdict and move control into a non-Agent planning/stop state."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow" / "control" / "WORKFLOW_STATE.yaml"


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
        raise SystemExit(f"expected exactly one {key}")
    return pattern.sub(f"{key}: {rendered}", text, count=1)


def replace_frontmatter_scalar(text: str, key: str, value: str) -> str:
    if not text.startswith("---\n"):
        raise SystemExit("review missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise SystemExit("review has unterminated frontmatter")
    head = text[:end]
    tail = text[end:]
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*.*$")
    if len(pattern.findall(head)) != 1:
        raise SystemExit(f"expected exactly one review frontmatter {key}")
    return pattern.sub(f"{key}: {value}", head, count=1) + tail


def replace_authorized_next_empty(text: str) -> str:
    inline = re.compile(r"(?m)^authorized_next:\s*\[\s*\]\s*$")
    if inline.search(text):
        return text
    block = re.compile(r"(?m)^authorized_next:\s*$\n(?:^[ \t]+-[^\n]*\n)*")
    if len(block.findall(text)) != 1:
        raise SystemExit("expected one authorized_next field")
    return block.sub("authorized_next: []\n", text, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record Architect Gate verdict.")
    parser.add_argument(
        "--verdict",
        required=True,
        choices=("PASS", "CHANGES_REQUIRED", "BLOCKED", "USER_ESCALATION"),
    )
    parser.add_argument(
        "--final",
        action="store_true",
        help="For PASS only: stop at PASS instead of entering ARCHITECT_PLANNING for a next task.",
    )
    args = parser.parse_args()

    if args.final and args.verdict != "PASS":
        raise SystemExit("--final is valid only with --verdict PASS")

    state_text = STATE.read_text(encoding="utf-8")
    task_key = scalar(state_text, "task_key")
    state_name = scalar(state_text, "state")
    owner = scalar(state_text, "owner")
    report_status = scalar(state_text, "report_status")
    review_status = scalar(state_text, "review_status")
    review_rel = scalar(state_text, "expected_review_file")
    handoff_seq = int(scalar(state_text, "handoff_seq"))

    if state_name != "REVIEW_READY" or owner != "architect":
        raise SystemExit(
            f"Architect verdict requires REVIEW_READY/architect, got {state_name}/{owner}"
        )
    if report_status != "REVIEW_READY" or review_status != "AWAITING_REVIEW":
        raise SystemExit(
            "Architect verdict requires report_status=REVIEW_READY and "
            "review_status=AWAITING_REVIEW"
        )

    review_path = ROOT / review_rel
    if not review_path.is_file():
        raise SystemExit(f"active review missing: {review_rel}")
    review_text = review_path.read_text(encoding="utf-8")
    review_text = replace_frontmatter_scalar(review_text, "status", args.verdict)
    review_text = re.sub(
        r"(?m)^(?:\x60)?AWAITING_REVIEW(?:\x60)?\s*$",
        chr(96) + args.verdict + chr(96),
        review_text,
        count=1,
    )

    new_seq = handoff_seq + 1
    handoff_id = f"{task_key}-architect-verdict-{new_seq:04d}"
    if args.verdict == "PASS":
        next_state = "PASS" if args.final else "ARCHITECT_PLANNING"
    elif args.verdict == "CHANGES_REQUIRED":
        next_state = "ARCHITECT_PLANNING"
    else:
        next_state = args.verdict

    state_text = replace_scalar(state_text, "handoff_seq", str(new_seq), quote=False)
    state_text = replace_scalar(state_text, "handoff_id", handoff_id)
    state_text = replace_scalar(state_text, "state", next_state)
    state_text = replace_scalar(state_text, "owner", "architect")
    state_text = replace_scalar(state_text, "report_status", "REVIEW_READY")
    state_text = replace_scalar(state_text, "review_status", args.verdict)
    state_text = replace_authorized_next_empty(state_text)

    review_path.write_text(review_text, encoding="utf-8", newline="\n")
    STATE.write_text(state_text, encoding="utf-8", newline="\n")

    print("ARCHITECT VERDICT PREPARED")
    print(f"  task_key: {task_key}")
    print(f"  verdict: {args.verdict}")
    print(f"  state: {next_state}")
    print(f"  handoff_id: {handoff_id}")
    if next_state == "ARCHITECT_PLANNING":
        print("Next: run scaffold_workflow_handoff.py for the next task/iteration.")
    else:
        print("Workflow stops here until an explicit new Architect action.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
