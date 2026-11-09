"""Pull-request filters. The first matching reason wins, and only one is kept.

A missing patch is not treated as a binary file. GitHub omits the patch for
large text diffs as well as for binaries.
"""

import re
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

_REVERT = re.compile(r"(?i)^\s*revert\b")
_CLOSING = re.compile(
    r"(?i)\b(?:closes|closed|close|fixes|fixed|fix|resolves|resolved|resolve)\s*:?\s+"
    r"(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#\d+\b"
)


def classify_pull(
    pull: PullPayload,
    files: list[PullFilePayload] | None,
) -> FilterReason | None:
    """Return the first rejection, or None when the pull passes every filter."""
    early = early_reason(pull)
    if early is not None:
        return early
    if files is None:
        raise ValueError("File list is required after the size filters pass.")
    if len(files) > MAX_CHANGED_FILES:
        return FilterReason.TOO_MANY_FILES
    return content_reason(pull, files)


def early_reason(pull: PullPayload) -> FilterReason | None:
    """Filters that can be decided from the pull list, before fetching files."""
    if pull.merged_at is None:
        return FilterReason.NOT_MERGED
    if _REVERT.match(pull.title) is not None:
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
    if any(is_binary(item) for item in files):
        return FilterReason.BINARY
    if any(is_lockfile(item.filename) for item in files):
        return FilterReason.LOCKFILE
    if files and all(is_documentation(item.filename) for item in files):
        return FilterReason.DOCS_ONLY
    has_source = any(is_source_file(item.filename) for item in files)
    has_test = any(is_test_file(item.filename) for item in files)
    if not has_source or not has_test:
        return FilterReason.MISSING_SOURCE_OR_TEST
    if not has_linked_issue(pull.body):
        return FilterReason.NO_LINKED_ISSUE
    return None


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
    """True when the body has a closing keyword immediately before an issue ref."""
    if body is None or body.strip() == "":
        return False
    return _CLOSING.search(body) is not None
