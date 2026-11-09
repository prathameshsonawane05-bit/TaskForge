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


class FilterReason(StrEnum):
    """One rejection per pull request. The funnel prints these in this order."""

    NOT_MERGED = "not_merged"
    REVERT = "revert"
    TOO_MANY_FILES = "too_many_files"
    TOO_MANY_LINES = "too_many_lines"
    UNKNOWN_SIZE = "unknown_size"
    BINARY = "binary"
    LOCKFILE = "lockfile"
    DOCS_ONLY = "docs_only"
    MISSING_SOURCE_OR_TEST = "missing_source_or_test"
    NO_LINKED_ISSUE = "no_linked_issue"


class PullPayload(BaseModel):
    """Fields used from a closed-pull list item. Extra GitHub fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    number: int
    title: str = ""
    body: str | None = None
    merged_at: str | None = None
    changed_files: int | None = None
    additions: int | None = None
    deletions: int | None = None


class PullFilePayload(BaseModel):
    """One file from the pull-request files API."""

    model_config = ConfigDict(extra="ignore")

    filename: str = Field(min_length=1)
    patch: str | None = None
    binary: bool | None = None


class FunnelCounts(BaseModel):
    """Rejection counts. Field order is the filter order."""

    model_config = ConfigDict(extra="forbid")

    not_merged: int = 0
    revert: int = 0
    too_many_files: int = 0
    too_many_lines: int = 0
    unknown_size: int = 0
    binary: int = 0
    lockfile: int = 0
    docs_only: int = 0
    missing_source_or_test: int = 0
    no_linked_issue: int = 0

    def total(self) -> int:
        return (
            self.not_merged
            + self.revert
            + self.too_many_files
            + self.too_many_lines
            + self.unknown_size
            + self.binary
            + self.lockfile
            + self.docs_only
            + self.missing_source_or_test
            + self.no_linked_issue
        )


class FunnelReport(BaseModel):
    """considered equals accepted plus every rejection count."""

    model_config = ConfigDict(extra="forbid")

    full_name: str
    limit: int
    considered: int
    counts: FunnelCounts
    accepted: int
    older_prs_cut_off: bool
