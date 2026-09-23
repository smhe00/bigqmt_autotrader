from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Mapping, Any


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class DeploymentMismatch(RuntimeError):
    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def canonical_config_digest(config: Mapping[str, Any]) -> str:
    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    payload = json.dumps(
        config,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ReleaseManifest:
    application_build: str
    git_commit: str
    schema_version: int
    terminal_instance_id: str
    qmt_bridge_build: str
    config_digest: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("application_build", "terminal_instance_id", "qmt_bridge_build"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if _GIT_SHA_RE.fullmatch(self.git_commit) is None:
            raise ValueError("git_commit must be a full lowercase 40-character SHA")
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise TypeError("schema_version must be int")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be > 0")
        if _SHA256_RE.fullmatch(self.config_digest) is None:
            raise ValueError("config_digest must be sha256:<64 lowercase hex>")
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True)
class ObservedDeployment:
    application_build: str
    git_commit: str
    binary_supported_schema_version: int
    database_schema_version: int
    terminal_instance_id: str
    qmt_bridge_build: str
    config_digest: str


@dataclass(frozen=True)
class DeploymentValidation:
    compatible: bool
    errors: tuple[str, ...]


class DeploymentGuard:
    """Validate one immutable release manifest against observed runtime state."""

    @staticmethod
    def validate(
        expected: ReleaseManifest,
        observed: ObservedDeployment,
    ) -> DeploymentValidation:
        if not isinstance(expected, ReleaseManifest):
            raise TypeError("expected must be ReleaseManifest")
        if not isinstance(observed, ObservedDeployment):
            raise TypeError("observed must be ObservedDeployment")

        errors: list[str] = []
        if observed.application_build != expected.application_build:
            errors.append("APPLICATION_BUILD_MISMATCH")
        if observed.git_commit != expected.git_commit:
            errors.append("GIT_COMMIT_MISMATCH")
        if observed.terminal_instance_id != expected.terminal_instance_id:
            errors.append("TERMINAL_INSTANCE_MISMATCH")
        if observed.qmt_bridge_build != expected.qmt_bridge_build:
            errors.append("QMT_BRIDGE_BUILD_MISMATCH")
        if observed.config_digest != expected.config_digest:
            errors.append("CONFIG_DIGEST_MISMATCH")

        if observed.binary_supported_schema_version != expected.schema_version:
            errors.append("BINARY_SCHEMA_CONTRACT_MISMATCH")
        if observed.database_schema_version > observed.binary_supported_schema_version:
            errors.append("DATABASE_SCHEMA_NEWER_THAN_BINARY")
        elif observed.database_schema_version < expected.schema_version:
            errors.append("DATABASE_SCHEMA_NOT_MIGRATED")

        return DeploymentValidation(
            compatible=not errors,
            errors=tuple(errors),
        )

    @staticmethod
    def assert_compatible(
        expected: ReleaseManifest,
        observed: ObservedDeployment,
    ) -> None:
        result = DeploymentGuard.validate(expected, observed)
        if not result.compatible:
            raise DeploymentMismatch(result.errors)
