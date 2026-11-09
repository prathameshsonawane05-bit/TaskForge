"""Split an accepted pull request into a source patch and a test patch.

Files that are neither source nor test are named and left out of both diffs.
A missing patch on a source or test file is an error, not an empty diff.
The linked issue is the first closing reference in the body, loaded with the
same GitHub client the funnel uses.
"""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from forge.check import check_repository
from forge.config import default_cache_path, load_github_token
from forge.errors import ForgeError, GitHubError
from forge.filters import (
    classify_pull,
    early_reason,
    first_closing_reference,
    is_source_file,
    is_test_file,
)
from forge.funnel import fetch_pull, fetch_pull_files
from forge.github import GitHubClient, issue_url
from forge.models import CheckResult, FilterReason, IssuePayload, PullFilePayload, ReasonCode

_NEEDS_QUOTES = re.compile(r'[\s"\\]')


@dataclass(frozen=True)
class SplitReport:
    """One accepted pull request, split, with the issue GitHub returned."""

    full_name: str
    number: int
    source_files: tuple[str, ...]
    test_files: tuple[str, ...]
    other_files: tuple[str, ...]
    source_patch: str
    test_patch: str
    issue_number: int
    issue_url: str
    issue_title: str
    issue_body: str | None


@dataclass(frozen=True)
class SplitRun:
    repo_refusal: CheckResult | None = None
    filter_reason: FilterReason | None = None
    report: SplitReport | None = None


def run_split(
    repo: str,
    number: int,
    *,
    root: Path,
    client: GitHubClient | None = None,
) -> SplitRun:
    if number < 1:
        raise ForgeError(
            "Pull request number must be a positive integer.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if client is not None:
        gate = check_repository(repo, root=root, client=client)
        if not gate.accepted:
            return SplitRun(repo_refusal=gate)
        return _split(gate.full_name, number, client)
    gate = check_repository(repo, root=root)
    if not gate.accepted:
        return SplitRun(repo_refusal=gate)
    token = load_github_token(root / ".env")
    with GitHubClient(token=token, cache_path=default_cache_path(root)) as owned:
        return _split(gate.full_name, number, owned)


def format_split(report: SplitReport) -> str:
    lines = [f"repo {report.full_name}", f"pull {report.number}"]
    lines.extend(f"source {name}" for name in report.source_files)
    lines.extend(f"test {name}" for name in report.test_files)
    if report.other_files:
        lines.extend(f"other {name}" for name in report.other_files)
    else:
        lines.append("other none")
    lines.append(f"issue {report.issue_url}")
    return "\n".join(lines)


def partition_files(
    files: list[PullFilePayload],
) -> tuple[list[PullFilePayload], list[PullFilePayload], list[PullFilePayload]]:
    """Source, test, and everything else. Test wins when a name matches both."""
    source: list[PullFilePayload] = []
    test: list[PullFilePayload] = []
    other: list[PullFilePayload] = []
    for item in files:
        if is_test_file(item.filename):
            test.append(item)
        elif is_source_file(item.filename):
            source.append(item)
        else:
            other.append(item)
    return source, test, other


def render_patch(files: list[PullFilePayload]) -> str:
    """Join one unified diff per file. A missing patch raises."""
    return "".join(render_file_diff(item) for item in files)


def render_file_diff(item: PullFilePayload) -> str:
    """Wrap one files-API patch with diff --git, ---, and +++ headers."""
    patch = item.patch
    if patch is None or patch == "":
        raise ForgeError(
            f"File {item.filename} has no patch, so a diff cannot be built.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    status = (item.status or "modified").lower()
    if status == "renamed":
        previous = item.previous_filename
        if previous is None or previous == "":
            raise ForgeError(
                f"Renamed file {item.filename} has no previous_filename.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        old = previous
        _reject_bad_path(old)
    else:
        old = item.filename
    new = item.filename
    _reject_bad_path(new)
    lines = [f"diff --git {_git_path('a/', old)} {_git_path('b/', new)}"]
    if status == "renamed":
        lines.append(f"rename from {_quote_path(old)}")
        lines.append(f"rename to {_quote_path(new)}")
    if status == "added":
        lines.append("new file mode 100644")
        lines.append("--- /dev/null")
        lines.append(f"+++ {_git_path('b/', new)}")
    elif status == "removed":
        lines.append("deleted file mode 100644")
        lines.append(f"--- {_git_path('a/', old)}")
        lines.append("+++ /dev/null")
    else:
        lines.append(f"--- {_git_path('a/', old)}")
        lines.append(f"+++ {_git_path('b/', new)}")
    body = patch if patch.endswith("\n") else f"{patch}\n"
    return "\n".join(lines) + "\n" + body


def _split(full_name: str, number: int, client: GitHubClient) -> SplitRun:
    owner, name = full_name.split("/", maxsplit=1)
    pull = fetch_pull(client, owner, name, number)
    if pull.number != number:
        raise GitHubError(
            "GitHub returned a different pull request than the one requested.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    early = early_reason(pull)
    if early is not None:
        return SplitRun(filter_reason=early)
    files = fetch_pull_files(client, owner, name, number)
    reason = classify_pull(pull, files)
    if reason is not None:
        return SplitRun(filter_reason=reason)
    reference = first_closing_reference(pull.body, repo_owner=owner, repo_name=name)
    if reference is None:
        raise ForgeError(
            "Accepted pull request had no closing reference.",
            reason=ReasonCode.INTERNAL,
        )
    issue = fetch_issue(client, reference.owner, reference.name, reference.number)
    source, test, other = partition_files(files)
    report = SplitReport(
        full_name=full_name,
        number=number,
        source_files=tuple(item.filename for item in source),
        test_files=tuple(item.filename for item in test),
        other_files=tuple(item.filename for item in other),
        source_patch=render_patch(source),
        test_patch=render_patch(test),
        issue_number=issue.number,
        issue_url=issue.html_url,
        issue_title=issue.title,
        issue_body=issue.body,
    )
    return SplitRun(report=report)


def fetch_issue(client: GitHubClient, owner: str, name: str, number: int) -> IssuePayload:
    document = client.get(issue_url(owner, name, number))
    if not isinstance(document.data, dict):
        raise GitHubError(
            "Issue payload was not a JSON object.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    try:
        payload = IssuePayload.model_validate(document.data)
    except ValidationError:
        raise GitHubError(
            "Issue payload was missing the number or URL.",
            reason=ReasonCode.GITHUB_ERROR,
        ) from None
    if payload.number != number:
        raise GitHubError(
            "GitHub returned a different issue than the one requested.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return payload


def _reject_bad_path(path: str) -> None:
    if path.startswith("/") or "\\" in path or "\n" in path or "\r" in path:
        raise ForgeError(
            f"Refusing to build a diff for path {path!r}.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    if any(part == ".." for part in PurePosixPath(path).parts):
        raise ForgeError(
            f"Refusing to build a diff for path {path!r}.",
            reason=ReasonCode.GITHUB_ERROR,
        )


def _git_path(prefix: str, path: str) -> str:
    return _quote_path(f"{prefix}{path}")


def _quote_path(path: str) -> str:
    if _NEEDS_QUOTES.search(path) is None:
        return path
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
