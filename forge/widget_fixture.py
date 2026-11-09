"""A small project used to classify tests. It is not a public benchmark."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from forge.errors import ForgeError
from forge.models import ReasonCode

WIDGET_PY = """\
def add(left: int, right: int) -> int:
    return left - right


def answer() -> int:
    return 1


def broken() -> None:
    raise RuntimeError("still broken")
"""

TEST_KEEP = """\
def test_truth() -> None:
    assert True
"""

TEST_ANSWER = """\
from widget import answer


def test_answer() -> None:
    assert answer() == 1
"""

TEST_STILL = """\
from widget import broken


def test_still_broken() -> None:
    broken()
"""

TEST_NEW = """\
import pytest

from widget import add


def test_add() -> None:
    assert add(1, 1) == 2


@pytest.mark.skip(reason="not a pass")
def test_skipped() -> None:
    assert False
"""

_SECRET_KEYS = frozenset({"GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"})


@dataclass(frozen=True)
class PreparedWidget:
    checkout: Path
    patches: Path
    sha: str


def prepare_widget(root: Path) -> PreparedWidget:
    """Commit the parent tree and write both patches beside it."""
    base = root / "data" / "fixtures" / "widget"
    if base.exists():
        shutil.rmtree(base)
    checkout = base / "repo"
    patches = base / "patches"
    tests = checkout / "tests"
    tests.mkdir(parents=True)
    patches.mkdir()
    (checkout / "widget.py").write_text(WIDGET_PY, encoding="utf-8")
    (tests / "test_keep.py").write_text(TEST_KEEP, encoding="utf-8")
    (tests / "test_answer.py").write_text(TEST_ANSWER, encoding="utf-8")
    (tests / "test_still.py").write_text(TEST_STILL, encoding="utf-8")
    _git(checkout, "init", "-b", "main")
    _git(checkout, "add", ".")
    _git(
        checkout,
        "-c",
        "user.email=fixture@taskforge.local",
        "-c",
        "user.name=taskforge",
        "commit",
        "-m",
        "base",
    )
    sha = _git(checkout, "rev-parse", "HEAD").strip().lower()
    if len(sha) != 40:
        raise ForgeError(
            "Fixture commit is not a full SHA.",
            reason=ReasonCode.INTERNAL,
        )
    new_test = tests / "test_new.py"
    new_test.write_text(TEST_NEW, encoding="utf-8")
    _git(checkout, "add", "-N", "tests/test_new.py")
    test_patch = _git(checkout, "diff", "--", "tests/test_new.py")
    _git(checkout, "reset", "-q")
    new_test.unlink()
    if "def test_add" not in test_patch:
        raise ForgeError(
            "Test patch does not add test_add.",
            reason=ReasonCode.INTERNAL,
        )
    source = checkout / "widget.py"
    original = source.read_text(encoding="utf-8")
    updated = _replace_once(original, "return left - right\n", "return left + right\n")
    updated = _replace_once(updated, "return 1\n", "return 2\n")
    source.write_text(updated, encoding="utf-8")
    solution_patch = _git(checkout, "diff", "--", "widget.py")
    source.write_text(original, encoding="utf-8")
    if "return left + right" not in solution_patch or "return 2" not in solution_patch:
        raise ForgeError(
            "Solution patch does not change add and answer.",
            reason=ReasonCode.INTERNAL,
        )
    if "return left - right" not in source.read_text(encoding="utf-8"):
        raise ForgeError(
            "Solution was written into the base tree.",
            reason=ReasonCode.INTERNAL,
        )
    (patches / "test.patch").write_text(test_patch, encoding="utf-8")
    (patches / "solution.patch").write_text(solution_patch, encoding="utf-8")
    if _git(checkout, "status", "--porcelain").strip():
        raise ForgeError(
            "Fixture worktree is not the parent commit.",
            reason=ReasonCode.INTERNAL,
        )
    return PreparedWidget(checkout=checkout, patches=patches, sha=sha)


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ForgeError(
            "Fixture source did not contain the expected line once.",
            reason=ReasonCode.INTERNAL,
        )
    return text.replace(old, new, 1)


def _git(dest: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(dest), *args],
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).replace("\n", " ").strip()
        raise ForgeError(
            f"git {' '.join(args)} failed. {detail}",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    return completed.stdout


def _git_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in _SECRET_KEYS
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    return env
