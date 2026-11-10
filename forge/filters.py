"""Pull-request filters. The first matching reason wins, and only one is kept.

A missing patch is not treated as a binary file. GitHub omits the patch for
large text diffs as well as for binaries.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from forge.models import FilterReason, PullFilePayload, PullPayload

MAX_CHANGED_FILES = 5
MAX_CHANGED_LINES = 300

# Basenames matched exactly, as GitHub reports them.
LOCKFILES = frozenset(
    {
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
        "pdm.lock",
        "package-lock.json",
        "yarn.lock",
        "Cargo.lock",
        "go.sum",
    }
)

# Suffixes treated as binary even when the files API omits `patch`.
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".pdf",
        ".zip",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".tar",
        ".wasm",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".class",
        ".jar",
        ".pyc",
        ".pyo",
        ".whl",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".webm",
        ".sqlite",
        ".db",
        ".pickle",
        ".pkl",
    }
)

DOC_SUFFIXES = frozenset({".md", ".rst", ".txt", ".adoc", ".asciidoc"})
DOC_BASENAMES = frozenset({"license", "copying", "authors", "changelog"})
DOC_DIRECTORIES = frozenset({"doc", "docs"})

_REVERT_TITLE = re.compile(r"(?i)^\s*revert\b")
# GitHub writes this sentence into the body of a revert commit.
_REVERT_BODY = "This reverts commit"
_KEYWORD = r"closes|closed|close|fixes|fixed|fix|resolves|resolved|resolve"
_ISSUE_URL = (
    r"https://github\.com/"
    r"(?P<url_owner>[A-Za-z0-9_.-]+)/(?P<url_name>[A-Za-z0-9_.-]+)"
    r"/issues/(?P<url_number>\d+)"
)
_HASH_REF = r"(?:(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+))?#(?P<number>\d+)"
_CLOSING = re.compile(rf"(?i)\b(?:{_KEYWORD})\s*:?\s+(?:{_ISSUE_URL}|{_HASH_REF})\b")


@dataclass(frozen=True)
class ClosingReference:
    """The first closing reference in a pull-request body."""

    owner: str
    name: str
    number: int


def classify_pull(
    pull: PullPayload,
    files: list[PullFilePayload] | None,
) -> FilterReason | None:
    """Return the first rejection, or None when the pull passes every filter."""
    return _decide(pull, files)[0]


def decision_evidence(
    pull: PullPayload,
    files: list[PullFilePayload] | None,
) -> str:
    """Describe the same reason :func:`classify_pull` returns.

    Binary, lockfile, and docs-only name the first file that caused them.
    A length or sum mismatch includes both numbers. An accept includes the
    issue number from the first closing reference.
    """
    return _decide(pull, files)[1]


def early_reason(pull: PullPayload) -> FilterReason | None:
    """Filters that can be decided from the pull list, before fetching files."""
    if pull.merged_at is None:
        return FilterReason.NOT_MERGED
    if _REVERT_TITLE.match(pull.title) is not None or _body_reverts(pull.body):
        return FilterReason.REVERT
    if pull.changed_files is None:
        return FilterReason.UNKNOWN_SIZE
    if pull.changed_files > MAX_CHANGED_FILES:
        return FilterReason.TOO_MANY_FILES
    if pull.additions is None or pull.deletions is None:
        return FilterReason.UNKNOWN_SIZE
    if pull.additions + pull.deletions > MAX_CHANGED_LINES:
        return FilterReason.TOO_MANY_LINES
    return None


def content_reason(pull: PullPayload, files: list[PullFilePayload]) -> FilterReason | None:
    return _content_decision(pull, files)[0]


def is_binary(item: PullFilePayload) -> bool:
    """An explicit binary flag or a known suffix. A missing patch is not enough."""
    if item.binary is True:
        return True
    return PurePosixPath(item.filename).suffix.lower() in BINARY_SUFFIXES


def is_lockfile(path: str) -> bool:
    return PurePosixPath(path).name in LOCKFILES


def is_documentation(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix.lower() in DOC_SUFFIXES:
        return True
    if pure.name.lower() in DOC_BASENAMES:
        return True
    return any(part.lower() in DOC_DIRECTORIES for part in pure.parts[:-1])


def is_test_file(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    if not name.endswith(".py"):
        return False
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part.lower() in {"test", "tests"} for part in pure.parts[:-1])


def is_source_file(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name.endswith(".py") and not is_test_file(path)


def has_linked_issue(body: str | None) -> bool:
    """True when a closing keyword sits immediately before an issue reference."""
    return _closing_match(body) is not None


def first_closing_reference(
    body: str | None,
    *,
    repo_owner: str,
    repo_name: str,
) -> ClosingReference | None:
    """Return the first closing reference. A bare ``#N`` is this pull request's repo."""
    match = _closing_match(body)
    if match is None:
        return None
    url_number = match.group("url_number")
    if url_number is not None:
        url_owner = match.group("url_owner")
        url_name = match.group("url_name")
        if url_owner is None or url_name is None:
            return None
        return ClosingReference(url_owner, url_name, int(url_number))
    number = match.group("number")
    if number is None:
        return None
    owner = match.group("owner") or repo_owner
    name = match.group("name") or repo_name
    return ClosingReference(owner, name, int(number))


def _closing_match(body: str | None) -> re.Match[str] | None:
    if body is None or body.strip() == "":
        return None
    return _CLOSING.search(body)


def _body_reverts(body: str | None) -> bool:
    return body is not None and _REVERT_BODY in body


def _decide(
    pull: PullPayload,
    files: list[PullFilePayload] | None,
) -> tuple[FilterReason | None, str]:
    early = early_reason(pull)
    if early is not None:
        return early, _early_evidence(pull, early)
    if files is None:
        raise ValueError("File list is required after the size filters pass.")
    if len(files) > MAX_CHANGED_FILES:
        return FilterReason.TOO_MANY_FILES, f"too_many_files {len(files)}"
    return _content_decision(pull, files)


def _content_decision(
    pull: PullPayload,
    files: list[PullFilePayload],
) -> tuple[FilterReason | None, str]:
    if pull.changed_files is not None and len(files) != pull.changed_files:
        text = f"unknown_size files {len(files)} changed_files {pull.changed_files}"
        return FilterReason.UNKNOWN_SIZE, text
    counted = _file_count_decision(pull, files)
    if counted is not None:
        return counted
    binary = next((item for item in files if is_binary(item)), None)
    if binary is not None:
        return FilterReason.BINARY, f"binary {binary.filename}"
    lock = next((item for item in files if is_lockfile(item.filename)), None)
    if lock is not None:
        return FilterReason.LOCKFILE, f"lockfile {lock.filename}"
    if files and all(is_documentation(item.filename) for item in files):
        return FilterReason.DOCS_ONLY, f"docs_only {files[0].filename}"
    has_source = any(is_source_file(item.filename) for item in files)
    has_test = any(is_test_file(item.filename) for item in files)
    if not has_source or not has_test:
        return FilterReason.MISSING_SOURCE_OR_TEST, "missing_source_or_test"
    if not has_linked_issue(pull.body):
        return FilterReason.NO_LINKED_ISSUE, "no_linked_issue"
    reference = first_closing_reference(pull.body, repo_owner="owner", repo_name="name")
    if reference is None:
        return None, "accepted"
    return None, f"accepted issue {reference.number}"


def _file_count_decision(
    pull: PullPayload,
    files: list[PullFilePayload],
) -> tuple[FilterReason, str] | None:
    """Compare per-file counts only when the files API sent them."""
    states = [_count_state(item) for item in files]
    if states and all(state == "both" for state in states):
        file_additions = sum(_required_count(item.additions) for item in files)
        file_deletions = sum(_required_count(item.deletions) for item in files)
        pull_additions = pull.additions
        pull_deletions = pull.deletions
        if pull_additions is None or pull_deletions is None:
            return FilterReason.UNKNOWN_SIZE, "unknown_size additions missing"
        if file_additions != pull_additions or file_deletions != pull_deletions:
            text = (
                f"unknown_size additions {file_additions} {pull_additions} "
                f"deletions {file_deletions} {pull_deletions}"
            )
            return FilterReason.UNKNOWN_SIZE, text
        return None
    if any(state != "none" for state in states):
        return FilterReason.UNKNOWN_SIZE, "unknown_size file counts incomplete"
    return None


def _count_state(item: PullFilePayload) -> str:
    has_additions = item.additions is not None
    has_deletions = item.deletions is not None
    if has_additions and has_deletions:
        return "both"
    if has_additions or has_deletions:
        return "partial"
    return "none"


def _required_count(value: int | None) -> int:
    if value is None:
        raise ValueError("file count missing after the completeness check")
    return value


def _early_evidence(pull: PullPayload, reason: FilterReason) -> str:
    if reason is FilterReason.TOO_MANY_FILES:
        return f"too_many_files {pull.changed_files}"
    if reason is FilterReason.TOO_MANY_LINES:
        additions = pull.additions or 0
        deletions = pull.deletions or 0
        return f"too_many_lines {additions + deletions}"
    if reason is FilterReason.UNKNOWN_SIZE:
        if pull.changed_files is None:
            return "unknown_size changed_files missing"
        if pull.additions is None:
            return "unknown_size additions missing"
        return "unknown_size deletions missing"
    return reason.value
