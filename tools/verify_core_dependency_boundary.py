#!/usr/bin/env python3
"""Enforce one-way Execution Core -> Production Runtime dependency direction."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "bigqmt_autotrader"

CORE_ROOTS = frozenset({"core", "domain", "drivers", "oms", "ports", "qmt"})
RUNTIME_ROOTS = frozenset(
    {"risk", "market_data", "operations", "service", "strategy_api", "runtime", "web"}
)


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


def _runtime_root(module: str | None) -> str | None:
    if not module:
        return None
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "bigqmt_autotrader":
        return None
    return parts[1]


def main() -> None:
    violations: list[str] = []
    scanned = 0

    for root_name in sorted(CORE_ROOTS):
        root = PACKAGE / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
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
                    runtime_root = _runtime_root(module)
                    if runtime_root in RUNTIME_ROOTS:
                        violations.append(
                            f"{relative}:{getattr(node, 'lineno', '?')} imports "
                            f"Production Runtime module {module}"
                        )

    if violations:
        raise SystemExit(
            "CORE/RUNTIME DEPENDENCY BOUNDARY FAILED\n" + "\n".join(violations)
        )

    print(
        "CORE/RUNTIME DEPENDENCY BOUNDARY PASS "
        f"({scanned} Core-plane Python files scanned)"
    )
    print("  Core roots: " + ", ".join(sorted(CORE_ROOTS)))
    print("  Forbidden Runtime roots: " + ", ".join(sorted(RUNTIME_ROOTS)))


if __name__ == "__main__":
    main()
