"""Shared result and GitHub payload models."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReasonCode(StrEnum):
    """Stable refusal and failure codes. Values are the CLI text."""

    NOT_ON_ALLOWLIST = "not_on_allowlist"
    LICENSE_MISSING = "license_missing"
    LICENSE_NOASSERTION = "license_noassertion"
    LICENSE_NOT_ALLOWED = "license_not_allowed"
    MISSING_TOKEN = "missing_token"
    RATE_LIMITED = "rate_limited"
    GITHUB_ERROR = "github_error"
    INVALID_REPO = "invalid_repo"
    CONFIG_ERROR = "config_error"
    INTERNAL = "internal"


ALLOWED_SPDX_IDS = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"})


class LicensePayload(BaseModel):
    """License object from GET /repos/{owner}/{repo}. Extra fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    spdx_id: str | None = None


class RepoPayload(BaseModel):
    """Fields the license check needs from a repository payload."""

    model_config = ConfigDict(extra="ignore")

    full_name: str = Field(min_length=1)
    license: LicensePayload | None = None


class CheckResult(BaseModel):
    """Outcome of checking one repository. A refusal is a result, not a crash."""

    model_config = ConfigDict(extra="forbid")

    full_name: str
    accepted: bool
    reason: ReasonCode | None = None
    spdx_id: str | None = None
