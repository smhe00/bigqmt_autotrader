from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05.py"
TOKEN = "__BIGQMT_INSTANCE_ID__"
DEPLOYMENTS = {
    "galaxy": ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py",
    "guojin": ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py",
    "guojin_sim": ROOT / "qmt_side" / "BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py",
}


def rendered(instance_id: str) -> bytes:
    source = TEMPLATE.read_text(encoding="utf-8")
    if source.count(TOKEN) != 1:
        raise RuntimeError("V05 deployment token must appear exactly once")
    return source.replace(TOKEN, instance_id).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build standalone broker-instance V05 scripts")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    for instance_id, target in DEPLOYMENTS.items():
        expected = rendered(instance_id)
        if args.check:
            if not target.is_file() or target.read_bytes() != expected:
                stale.append(str(target.relative_to(ROOT)))
        else:
            target.write_bytes(expected)
    if stale:
        raise SystemExit("stale QMT deployment files: " + ", ".join(stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
