#!/usr/bin/env python3
"""Enforce Production Runtime -> Core public API execution boundary."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "bigqmt_autotrader"
RUNTIME_ROOTS = frozenset(
    {"risk", "market_data", "operations", "service", "strategy_api", "runtime", "web"}
)
FORBIDDEN_IMPLEMENTATION_ROOTS = frozenset({"oms", "qmt", "drivers"})


def _module_for(path: Path) -> list[str]:
    relative = path.relative_to(PACKAGE).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ["bigqmt_autotrader", *parts]


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    current = _module_for(path)
    package_parts = current if path.name == "__init__.py" else current[:-1]
    up = node.level - 1
    if up > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - up]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _runtime_files():
    for root_name in sorted(RUNTIME_ROOTS):
        root = PACKAGE / root_name
        if root.is_dir():
            yield from sorted(root.rglob("*.py"))


def main() -> None:
    violations: list[str] = []
    scanned = 0

    for path in _runtime_files():
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(PACKAGE).as_posix()

        for node in ast.walk(tree):
            modules: list[str | None] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(_resolve_import_from(path, node))

            for module in modules:
                if not module or not module.startswith("bigqmt_autotrader."):
                    continue
                parts = module.split(".")
                if len(parts) < 2:
                    continue
                root = parts[1]

                if root in FORBIDDEN_IMPLEMENTATION_ROOTS:
                    violations.append(
                        f"{relative}:{getattr(node, 'lineno', '?')} imports "
                        f"execution implementation {module}; use "
                        "bigqmt_autotrader.core public API"
                    )

                if root == "core" and len(parts) > 2:
                    violations.append(
                        f"{relative}:{getattr(node, 'lineno', '?')} imports "
                        f"private Core module {module}; import only "
                        "bigqmt_autotrader.core"
                    )

    if violations:
        raise SystemExit(
            "RUNTIME/CORE PUBLIC API BOUNDARY FAILED\n" + "\n".join(violations)
        )

    print(
        "RUNTIME/CORE PUBLIC API BOUNDARY PASS "
        f"({scanned} Runtime-plane Python files scanned)"
    )


if __name__ == "__main__":
    main()
