from pathlib import Path

import pytest

from bigqmt_autotrader.qmt.spool import default_spool_root


def test_default_spool_root_uses_terminal_instance_namespace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BIGQMT_SPOOL_DIR", raising=False)
    monkeypatch.setenv("BIGQMT_SPOOL_BASE", str(tmp_path))
    monkeypatch.setenv("BIGQMT_INSTANCE_ID", "galaxy")

    assert default_spool_root() == tmp_path / "galaxy"


@pytest.mark.parametrize("instance_id", ["Galaxy", "../galaxy", "galaxy/other", ""])
def test_default_spool_root_rejects_unsafe_instance_namespace(
    tmp_path: Path, monkeypatch, instance_id: str
) -> None:
    monkeypatch.delenv("BIGQMT_SPOOL_DIR", raising=False)
    monkeypatch.setenv("BIGQMT_SPOOL_BASE", str(tmp_path))
    monkeypatch.setenv("BIGQMT_INSTANCE_ID", instance_id)

    with pytest.raises(ValueError):
        default_spool_root()


def test_explicit_spool_root_remains_exact_override(tmp_path: Path, monkeypatch) -> None:
    exact = tmp_path / "guojin"
    monkeypatch.setenv("BIGQMT_SPOOL_DIR", str(exact))
    monkeypatch.setenv("BIGQMT_SPOOL_BASE", str(tmp_path / "ignored"))
    monkeypatch.setenv("BIGQMT_INSTANCE_ID", "galaxy")

    assert default_spool_root() == exact
