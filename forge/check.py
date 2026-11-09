"""Decide whether one repository is allowed.

Allowlist membership is checked first and does not call GitHub. An allowlisted
repository is still refused when the API license is missing or not one of the
four permissive SPDX ids.
"""

import re
from pathlib import Path

from forge.allowlist import load_allowlist
from forge.config import allowlist_path, default_cache_path, load_github_token
from forge.errors import ForgeError, GitHubError
from forge.github import GitHubClient
from forge.models import ALLOWED_SPDX_IDS, CheckResult, ReasonCode, RepoPayload

_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def check_repository(
    repo: str,
    *,
    root: Path,
    client: GitHubClient | None = None,
) -> CheckResult:
    full_name = parse_full_name(repo)
    allowlist = load_allowlist(allowlist_path(root))
    if not allowlist.contains(full_name):
        return CheckResult(
            full_name=full_name,
            accepted=False,
            reason=ReasonCode.NOT_ON_ALLOWLIST,
        )
    owner, name = full_name.split("/", maxsplit=1)
    if client is None:
        token = load_github_token(root / ".env")
        with GitHubClient(token=token, cache_path=default_cache_path(root)) as owned:
            payload = owned.get_repository(owner, name)
    else:
        payload = client.get_repository(owner, name)
    if payload.full_name.casefold() != full_name.casefold():
        raise GitHubError(
            "GitHub returned a different repository than the one requested.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return decide_license(payload.full_name, payload)


def decide_license(full_name: str, repo: RepoPayload) -> CheckResult:
    """Map a repository payload to an accept or a specific refusal."""
    info = repo.license
    if info is None or info.spdx_id is None or info.spdx_id.strip() == "":
        return CheckResult(
            full_name=full_name,
            accepted=False,
            reason=ReasonCode.LICENSE_MISSING,
        )
    spdx_id = info.spdx_id.strip()
    if spdx_id == "NOASSERTION":
        return CheckResult(
            full_name=full_name,
            accepted=False,
            reason=ReasonCode.LICENSE_NOASSERTION,
            spdx_id=spdx_id,
        )
    if spdx_id not in ALLOWED_SPDX_IDS:
        return CheckResult(
            full_name=full_name,
            accepted=False,
            reason=ReasonCode.LICENSE_NOT_ALLOWED,
            spdx_id=spdx_id,
        )
    return CheckResult(full_name=full_name, accepted=True, spdx_id=spdx_id)


def parse_full_name(repo: str) -> str:
    parts = repo.split("/")
    if len(parts) != 2 or not _valid_segment(parts[0]) or not _valid_segment(parts[1]):
        raise ForgeError(
            "Repository must be owner/name using letters, numbers, dots, underscores, or hyphens.",
            reason=ReasonCode.INVALID_REPO,
        )
    return f"{parts[0]}/{parts[1]}"


def _valid_segment(segment: str) -> bool:
    if segment in {".", ".."}:
        return False
    return _SEGMENT.fullmatch(segment) is not None
