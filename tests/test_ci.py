"""The CI workflow runs the local checks and carries no token."""

import re
from pathlib import Path

from forge.config import find_repo_root

_COMMANDS = (
    "ruff check forge tests",
    "mypy",
    "pytest",
)
_TOKEN_VALUE = re.compile(r"ghp_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+")


def test_ci_runs_ruff_mypy_and_pytest_without_a_token() -> None:
    path = Path(".github") / "workflows" / "ci.yml"
    text = (find_repo_root() / path).read_text(encoding="utf-8")
    for command in _COMMANDS:
        assert f"run: {command}" in text
    assert _TOKEN_VALUE.search(text) is None
    assert "GITHUB_TOKEN" not in text
