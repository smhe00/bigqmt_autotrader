#!/usr/bin/env python3
"""Fail CI if production broker side-effect calls escape the fenced OMS boundary."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "bigqmt_autotrader"

ALLOWED = {
    "submit_limit_order": {
        ("oms/service.py", "submit_intent"),
    },
    "cancel_order": {
        ("oms/service.py", "cancel_order"),
    },
}


class CallVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.function_stack: list[str] = []
        self.calls: list[tuple[str, str, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in ALLOWED:
            enclosing = self.function_stack[-1] if self.function_stack else "<module>"
            self.calls.append((node.func.attr, enclosing, node.lineno))
        self.generic_visit(node)


def main() -> None:
    observed: dict[str, set[tuple[str, str]]] = {name: set() for name in ALLOWED}
    violations: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = CallVisitor(relative)
        visitor.visit(tree)

        for method, function, line in visitor.calls:
            location = (relative, function)
            observed[method].add(location)
            if location not in ALLOWED[method]:
                violations.append(
                    f"unauthorized production call {method} at {relative}:{line} in {function}()"
                )

    for method, expected_locations in ALLOWED.items():
        missing = expected_locations - observed[method]
        for relative, function in sorted(missing):
            violations.append(
                f"expected controlled call {method} missing from {relative}:{function}()"
            )

    if violations:
        raise SystemExit("SIDE-EFFECT SURFACE AUDIT FAILED\n" + "\n".join(violations))

    print("SIDE-EFFECT SURFACE AUDIT PASS")
    for method, locations in observed.items():
        rendered = ", ".join(f"{path}:{fn}()" for path, fn in sorted(locations))
        print(f"  {method}: {rendered}")


if __name__ == "__main__":
    main()
