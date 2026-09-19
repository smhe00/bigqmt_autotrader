import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _bridge_build(filename: str) -> str:
    source = (ROOT / "qmt_side" / filename).read_text(encoding="utf-8")
    match = re.search(r'^BRIDGE_BUILD = "([^"]+)"$', source, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_current_documents_name_the_generated_simulation_and_live_builds():
    simulation_build = _bridge_build("BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py")
    live_canary_build = _bridge_build("BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py")
    documents = (
        "README.md",
        "docs/PROJECT_OVERVIEW_ZH.md",
        "docs/PROJECT_STATUS.md",
        "docs/FORMAL_VERIFICATION.md",
    )

    for filename in documents:
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert simulation_build in text, filename
        assert live_canary_build in text, filename


def test_current_documents_do_not_restore_superseded_runtime_claims():
    current_text = "\n".join(
        (ROOT / filename).read_text(encoding="utf-8")
        for filename in (
            "README.md",
            "docs/PROJECT_OVERVIEW_ZH.md",
            "docs/PROJECT_STATUS.md",
            "docs/FORMAL_VERIFICATION.md",
        )
    )

    assert "| LIVE_CANARY | **未启用**" not in current_text
    assert "current build-5 gate" not in current_text
    assert "NOT YET DEPLOYED/CALIBRATED" not in current_text
