#!/usr/bin/env python3
"""Fail CI if production side-effect or evidence-write calls escape OMS boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "bigqmt_autotrader"

ALLOWED_ATTRIBUTE_CALLS = {
    "submit_limit_order": {
        ("oms/service.py", "submit_intent"),
    },
    "cancel_order": {
        ("oms/service.py", "cancel_order"),
    },
    "merge_broker_fact_in_tx": {
        ("oms/evidence.py", "ingest"),
    },
}

ALLOWED_CONSTRUCTORS = {
    "EvidenceJournal": {
        ("oms/service.py", "__init__"),
    },
}


class CallVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.function_stack: list[str] = []
        self.attribute_calls: list[tuple[str, str, int]] = []
        self.constructor_calls: list[tuple[str, str, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        enclosing = self.function_stack[-1] if self.function_stack else "<module>"
        if isinstance(node.func, ast.Attribute) and node.func.attr in ALLOWED_ATTRIBUTE_CALLS:
            self.attribute_calls.append((node.func.attr, enclosing, node.lineno))
        if isinstance(node.func, ast.Name) and node.func.id in ALLOWED_CONSTRUCTORS:
            self.constructor_calls.append((node.func.id, enclosing, node.lineno))
        self.generic_visit(node)


def _audit_calls(
    observed: dict[str, set[tuple[str, str]]],
    allowed: dict[str, set[tuple[str, str]]],
    calls: list[tuple[str, str, int]],
    relative: str,
    violations: list[str],
    *,
    label: str,
) -> None:
    for name, function, line in calls:
        location = (relative, function)
        observed[name].add(location)
        if location not in allowed[name]:
            violations.append(
                f"unauthorized production {label} {name} at {relative}:{line} in {function}()"
            )


def main() -> None:
    observed_attributes: dict[str, set[tuple[str, str]]] = {
        name: set() for name in ALLOWED_ATTRIBUTE_CALLS
    }
    observed_constructors: dict[str, set[tuple[str, str]]] = {
        name: set() for name in ALLOWED_CONSTRUCTORS
    }
    violations: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = CallVisitor(relative)
        visitor.visit(tree)

        _audit_calls(
            observed_attributes,
            ALLOWED_ATTRIBUTE_CALLS,
            visitor.attribute_calls,
            relative,
            violations,
            label="call",
        )
        _audit_calls(
            observed_constructors,
            ALLOWED_CONSTRUCTORS,
            visitor.constructor_calls,
            relative,
            violations,
            label="constructor",
        )

    for allowed, observed in (
        (ALLOWED_ATTRIBUTE_CALLS, observed_attributes),
        (ALLOWED_CONSTRUCTORS, observed_constructors),
    ):
        for name, expected_locations in allowed.items():
            missing = expected_locations - observed[name]
            for relative, function in sorted(missing):
                violations.append(
                    f"expected controlled surface {name} missing from {relative}:{function}()"
                )

    if violations:
        raise SystemExit("SIDE-EFFECT SURFACE AUDIT FAILED\n" + "\n".join(violations))

    print("SIDE-EFFECT SURFACE AUDIT PASS")
    for name, locations in observed_attributes.items():
        rendered = ", ".join(f"{path}:{fn}()" for path, fn in sorted(locations))
        print(f"  call {name}: {rendered}")
    for name, locations in observed_constructors.items():
        rendered = ", ".join(f"{path}:{fn}()" for path, fn in sorted(locations))
        print(f"  constructor {name}: {rendered}")


if __name__ == "__main__":
    main()
