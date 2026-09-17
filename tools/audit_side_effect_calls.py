#!/usr/bin/env python3
"""Fail CI if production side-effect, risk-bypass or evidence-write calls escape OMS boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "bigqmt_autotrader"
QMT_SIDE = ROOT / "qmt_side"

ALLOWED_ATTRIBUTE_CALLS = {
    "submit_limit_order": {
        ("oms/service.py", "_submit_decided_intent"),
    },
    "cancel_order": {
        ("oms/service.py", "cancel_order"),
    },
    "merge_broker_fact_in_tx": {
        ("oms/evidence.py", "ingest"),
    },
    "_submit_decided_intent": {
        ("oms/service.py", "submit_intent"),
    },
}

ALLOWED_DIRECT_CALLS = {
    "evaluate_risk": {
        ("oms/service.py", "submit_intent"),
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
        self.direct_calls: list[tuple[str, str, int]] = []
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
        if isinstance(node.func, ast.Name) and node.func.id in ALLOWED_DIRECT_CALLS:
            self.direct_calls.append((node.func.id, enclosing, node.lineno))
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
    observed_attributes = {name: set() for name in ALLOWED_ATTRIBUTE_CALLS}
    observed_direct = {name: set() for name in ALLOWED_DIRECT_CALLS}
    observed_constructors = {name: set() for name in ALLOWED_CONSTRUCTORS}
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
            label="attribute call",
        )
        _audit_calls(
            observed_direct,
            ALLOWED_DIRECT_CALLS,
            visitor.direct_calls,
            relative,
            violations,
            label="direct call",
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
        (ALLOWED_DIRECT_CALLS, observed_direct),
        (ALLOWED_CONSTRUCTORS, observed_constructors),
    ):
        for name, expected_locations in allowed.items():
            missing = expected_locations - observed[name]
            for relative, function in sorted(missing):
                violations.append(
                    f"expected controlled surface {name} missing from {relative}:{function}()"
                )

    qmt_mutation_names = {
        "passorder",
        "cancel",
        "order_lots",
        "algo_passorder",
        "smart_algo_passorder",
        "cancel_task",
        "pause_task",
        "resume_task",
    }
    qmt_paths = {
        "template": QMT_SIDE / "BIGQMT_EXECUTION_BRIDGE_V05.py",
        "galaxy": QMT_SIDE / "BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py",
        "guojin": QMT_SIDE / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py",
        "guojin_sim": QMT_SIDE / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py",
    }
    qmt_observed: dict[str, list[tuple[str, str, int]]] = {}
    for deployment, path in qmt_paths.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls: list[tuple[str, str, int]] = []
        function_stack: list[str] = []

        class QmtVisitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                function_stack.append(node.name)
                self.generic_visit(node)
                function_stack.pop()

            def visit_Call(self, node: ast.Call) -> None:
                if isinstance(node.func, ast.Name) and node.func.id in qmt_mutation_names:
                    calls.append(
                        (
                            node.func.id,
                            function_stack[-1] if function_stack else "<module>",
                            node.lineno,
                        )
                    )
                self.generic_visit(node)

        QmtVisitor().visit(tree)
        qmt_observed[deployment] = calls

    for deployment in ("template", "galaxy"):
        for name, function, line in qmt_observed[deployment]:
            violations.append(
                f"broker mutation {name} escaped into {deployment} QMT artifact at "
                f"{function}():{line}"
            )
    expected_mutation_calls = {
        ("passorder", "_execute_order_command"),
        ("cancel", "_execute_order_command"),
    }
    for deployment in ("guojin", "guojin_sim"):
        calls = qmt_observed[deployment]
        observed_calls = {(name, function) for name, function, _line in calls}
        if observed_calls != expected_mutation_calls or len(calls) != 2:
            violations.append(
                deployment + " QMT mutation surface must contain exactly one passorder "
                "and one cancel call inside _execute_order_command()"
            )

    if violations:
        raise SystemExit("SIDE-EFFECT SURFACE AUDIT FAILED\n" + "\n".join(violations))

    print("SIDE-EFFECT SURFACE AUDIT PASS")
    for group, observed in (
        ("attribute call", observed_attributes),
        ("direct call", observed_direct),
        ("constructor", observed_constructors),
    ):
        for name, locations in observed.items():
            rendered = ", ".join(f"{path}:{fn}()" for path, fn in sorted(locations))
            print(f"  {group} {name}: {rendered}")
    print("  qmt simulation mutation calls: guojin_sim:_execute_order_command(passorder,cancel)")
    print("  qmt live canary mutation calls: guojin:_execute_order_command(passorder,cancel)")
    print("  qmt disabled mutation calls: template=0, galaxy=0")


if __name__ == "__main__":
    main()
