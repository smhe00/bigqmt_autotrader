from datetime import datetime, timedelta, timezone

import pytest

from bigqmt_autotrader.service import (
    DeploymentGuard,
    DeploymentMismatch,
    ObservedDeployment,
    ReleaseManifest,
    canonical_config_digest,
)


NOW = datetime(2026, 9, 23, 14, 30, tzinfo=timezone(timedelta(hours=8)))
SHA = "a" * 40


def expected():
    return ReleaseManifest(
        application_build="host-prod-readiness-1",
        git_commit=SHA,
        schema_version=10,
        terminal_instance_id="guojin_sim",
        qmt_bridge_build="p5-simulation-calibration-8",
        config_digest=canonical_config_digest(
            {"account": "fingerprint-only", "mode": "SIMULATION"}
        ),
        created_at=NOW,
    )


def observed(**changes):
    exp = expected()
    values = dict(
        application_build=exp.application_build,
        git_commit=exp.git_commit,
        binary_supported_schema_version=10,
        database_schema_version=10,
        terminal_instance_id=exp.terminal_instance_id,
        qmt_bridge_build=exp.qmt_bridge_build,
        config_digest=exp.config_digest,
    )
    values.update(changes)
    return ObservedDeployment(**values)


def test_exact_release_identity_is_compatible():
    result = DeploymentGuard.validate(expected(), observed())
    assert result.compatible
    assert result.errors == ()


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"application_build": "other"}, "APPLICATION_BUILD_MISMATCH"),
        ({"git_commit": "b" * 40}, "GIT_COMMIT_MISMATCH"),
        ({"terminal_instance_id": "guojin"}, "TERMINAL_INSTANCE_MISMATCH"),
        ({"qmt_bridge_build": "old-build"}, "QMT_BRIDGE_BUILD_MISMATCH"),
        (
            {"config_digest": "sha256:" + "b" * 64},
            "CONFIG_DIGEST_MISMATCH",
        ),
    ],
)
def test_identity_mismatch_fails_closed(changes, error):
    result = DeploymentGuard.validate(expected(), observed(**changes))
    assert not result.compatible
    assert error in result.errors


def test_old_binary_cannot_open_newer_database_after_rollback():
    result = DeploymentGuard.validate(
        expected(),
        observed(
            binary_supported_schema_version=9,
            database_schema_version=10,
        ),
    )
    assert not result.compatible
    assert "BINARY_SCHEMA_CONTRACT_MISMATCH" in result.errors
    assert "DATABASE_SCHEMA_NEWER_THAN_BINARY" in result.errors


def test_unmigrated_database_cannot_arm_new_binary():
    result = DeploymentGuard.validate(
        expected(),
        observed(database_schema_version=9),
    )
    assert not result.compatible
    assert result.errors == ("DATABASE_SCHEMA_NOT_MIGRATED",)


def test_assert_compatible_raises_with_all_reasons():
    with pytest.raises(DeploymentMismatch) as exc:
        DeploymentGuard.assert_compatible(
            expected(),
            observed(
                qmt_bridge_build="wrong",
                config_digest="sha256:" + "c" * 64,
            ),
        )
    assert exc.value.errors == (
        "QMT_BRIDGE_BUILD_MISMATCH",
        "CONFIG_DIGEST_MISMATCH",
    )


def test_config_digest_is_order_independent():
    assert canonical_config_digest({"a": 1, "b": 2}) == canonical_config_digest(
        {"b": 2, "a": 1}
    )
