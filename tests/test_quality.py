"""V6, V7, and V8 can each fail. These tests do not call Docker."""

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

from forge.config import find_repo_root
from forge.package import build_instruction, package_fixture
from forge.quality import (
    FAIL_ASSERTION,
    FAIL_IMPORT,
    FAIL_OTHER,
    QualityReport,
    check_quality,
    classify_failure,
    exact_error_messages,
    format_quality,
    leaked_line,
)
from forge.sandbox import CommandResult
from forge.widget_fixture import COUNTER_ISSUE, prepare_counter
from tests.fakes import write_project

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"

SOLUTION = """\
diff --git a/counter.py b/counter.py
--- a/counter.py
+++ b/counter.py
@@ -1,2 +1,2 @@
 def value() -> int:
-    return 0
+    return 1
"""

ASSERT_BEFORE = """\
tests/test_keep.py::test_truth PASSED
tests/test_value.py::test_value FAILED
FAILED tests/test_value.py::test_value - assert 0 == 1
"""

IMPORT_BEFORE = """\
FAILED tests/test_new.py::test_add - AttributeError: module 'widget' has no attribute 'add'
"""

COUNTER_LOG = f"""\
SOLUTION_CHECK:absent
BEFORE_STATUS:1
AFTER_STATUS:0
---BEFORE-STDOUT---
{ASSERT_BEFORE}---BEFORE-STDERR---
---AFTER-STDOUT---
tests/test_keep.py::test_truth PASSED
tests/test_value.py::test_value PASSED
---AFTER-STDERR---
"""

WIDGET_LOG = """\
SOLUTION_CHECK:absent
BEFORE_STATUS:1
AFTER_STATUS:1
---BEFORE-STDOUT---
tests/test_new.py::test_add FAILED
tests/test_keep.py::test_truth PASSED
tests/test_answer.py::test_answer PASSED
tests/test_still.py::test_still_broken FAILED
tests/test_new.py::test_skipped SKIPPED (not a pass)
FAILED tests/test_new.py::test_add - assert 0 == 2
FAILED tests/test_still.py::test_still_broken - RuntimeError: still broken
---BEFORE-STDERR---
---AFTER-STDOUT---
tests/test_new.py::test_add PASSED
tests/test_keep.py::test_truth PASSED
tests/test_answer.py::test_answer FAILED
tests/test_still.py::test_still_broken FAILED
tests/test_new.py::test_skipped SKIPPED (not a pass)
---AFTER-STDERR---
"""


class Recorder:
    def __init__(self, logs: str) -> None:
        self.logs = logs

    def __call__(
        self,
        args: list[str],
        env: Mapping[str, str],
        timeout: float | None,
    ) -> CommandResult:
        del env, timeout
        if args[:2] == ["docker", "wait"]:
            return CommandResult(0, "0\n", "")
        if args[:2] == ["docker", "logs"]:
            return CommandResult(0, self.logs, "")
        if args[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            return CommandResult(0, "Platform: linux/arm64/v8\n", "")
        return CommandResult(0, "", "")


def test_import_failure_without_a_signature_is_unfair() -> None:
    instruction = "The add function is missing.\n"
    report = check_quality(
        before_stdout=IMPORT_BEFORE,
        fail_to_pass=("tests/test_new.py::test_add",),
        instruction=instruction,
        solution_patch=SOLUTION,
        test_patch="",
    )
    assert classify_failure(IMPORT_BEFORE) == FAIL_IMPORT
    assert report.unfair == ("tests/test_new.py::test_add",)
    assert report.clean is False


def test_import_failure_with_a_signature_is_fair() -> None:
    instruction = "Implement add(left: int, right: int) -> int.\n"
    report = check_quality(
        before_stdout=IMPORT_BEFORE,
        fail_to_pass=("tests/test_new.py::test_add",),
        instruction=instruction,
        solution_patch=SOLUTION,
        test_patch="",
    )
    assert report.unfair == ()
    assert report.failures == (("tests/test_new.py::test_add", FAIL_IMPORT),)


def test_behavior_sentence_is_not_the_solution_line() -> None:
    instruction = build_instruction(COUNTER_ISSUE)
    assert "value() should return 1" in instruction
    assert leaked_line(SOLUTION, instruction) is None
    leaked = leaked_line(SOLUTION, instruction + "return 1\n")
    assert leaked is not None
    assert leaked.strip() == "return 1"


def test_missing_exact_error_string_is_hidden() -> None:
    test_patch = 'with pytest.raises(ValueError, match="missing value"):\n    value()\n'
    report = check_quality(
        before_stdout=ASSERT_BEFORE,
        fail_to_pass=("tests/test_value.py::test_value",),
        instruction=build_instruction(COUNTER_ISSUE),
        solution_patch=SOLUTION,
        test_patch=test_patch,
    )
    assert report.hidden == ("missing value",)
    present = check_quality(
        before_stdout=ASSERT_BEFORE,
        fail_to_pass=("tests/test_value.py::test_value",),
        instruction="The error says missing value.\n",
        solution_patch=SOLUTION,
        test_patch=test_patch,
    )
    assert present.hidden == ()


def test_return_value_assert_is_not_an_error_message() -> None:
    test_patch = "def test_value() -> None:\n    assert value() == 1\n"
    assert exact_error_messages(test_patch) == ()
    equality = 'assert str(exc) == "missing value"\n'
    assert exact_error_messages(equality) == ("missing value",)


def test_mixed_failure_kinds_are_named() -> None:
    report = QualityReport(
        failures=(
            ("tests/test_a.py::test_one", FAIL_ASSERTION),
            ("tests/test_b.py::test_two", FAIL_IMPORT),
        ),
        unfair=(),
        leaked_line=None,
        hidden=(),
    )
    header = format_quality(report).splitlines()[0]
    assert header == "v6 assertion, import_or_attribute"
    assert header != "v6 other"


def test_a_single_other_failure_keeps_that_name() -> None:
    report = QualityReport(
        failures=(("tests/test_a.py::test_one", FAIL_OTHER),),
        unfair=(),
        leaked_line=None,
        hidden=(),
    )
    assert format_quality(report).splitlines()[0] == "v6 other"


def test_assertion_failure_is_not_unfair() -> None:
    report = check_quality(
        before_stdout=ASSERT_BEFORE,
        fail_to_pass=("tests/test_value.py::test_value",),
        instruction=build_instruction(COUNTER_ISSUE),
        solution_patch=SOLUTION,
        test_patch="def test_value() -> None:\n    assert value() == 1\n",
    )
    assert report.failures == (("tests/test_value.py::test_value", FAIL_ASSERTION),)
    assert report.clean is True
    assert classify_failure(ASSERT_BEFORE) == FAIL_ASSERTION


def test_committed_sample_matches_a_fresh_fixture(tmp_path: Path) -> None:
    root = find_repo_root()
    sample = root / "output" / "sample" / "local-counter"
    prepared = prepare_counter(tmp_path)
    task = json.loads((sample / "task.json").read_text(encoding="utf-8"))
    assert task["base_commit"] == prepared.sha
    assert (sample / "solution" / "solution.patch").read_text(encoding="utf-8") == (
        prepared.patches / "solution.patch"
    ).read_text(encoding="utf-8")
    assert (sample / "tests" / "test.patch").read_text(encoding="utf-8") == (
        prepared.patches / "test.patch"
    ).read_text(encoding="utf-8")
    instruction = (sample / "instruction.md").read_text(encoding="utf-8")
    assert instruction == build_instruction(COUNTER_ISSUE)


def test_fixture_commit_date_is_pinned(tmp_path: Path) -> None:
    first = prepare_counter(tmp_path)
    second = prepare_counter(tmp_path / "other")
    assert first.sha == second.sha
    author = subprocess.run(
        ["git", "-C", str(first.checkout), "log", "-1", "--format=%at"],
        check=True,
        capture_output=True,
        text=True,
    )
    committer = subprocess.run(
        ["git", "-C", str(first.checkout), "log", "-1", "--format=%ct"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert author.stdout.strip() == "1577836800"
    assert committer.stdout.strip() == "1577836800"


def test_widget_is_not_packaged(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    result = package_fixture(
        "widget",
        root=tmp_path,
        executor=Recorder(WIDGET_LOG),
        base_env={"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN},
        host_platform="linux/arm64",
    )
    assert result.written is False
    assert result.report.reason is not None
    assert result.report.reason.value == "regression"
    assert not (tmp_path / "output" / "sample").exists()


def test_counter_package_is_clean(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    result = package_fixture(
        "counter",
        root=tmp_path,
        executor=Recorder(COUNTER_LOG),
        base_env={"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN},
        host_platform="linux/arm64",
    )
    assert result.written is True
    assert result.quality is not None
    assert result.quality.clean is True
    assert result.quality.failures[0][1] == FAIL_ASSERTION
    directory = result.directory
    assert directory is not None
    task = json.loads((directory / "task.json").read_text(encoding="utf-8"))
    assert task["task_id"] == "local-counter"
    assert task["repo"] == "local/counter"
    assert task["license"] == "no upstream"
    assert task["pr_url"] == "no upstream"
    assert task["issue_url"] == "no upstream"
    assert task["base_commit"] == result.report.sha
    assert "estimate" in task["difficulty_signals"]
    assert "not run against an agent" in task["difficulty_signals"]
    assert task["f2p"] == ["tests/test_value.py::test_value"]
    assert task["p2p"] == ["tests/test_keep.py::test_truth"]
    instruction = (directory / "instruction.md").read_text(encoding="utf-8")
    assert "return 1" not in {line.strip() for line in instruction.splitlines()}
    assert "value() should return 1" in instruction
    config = json.loads((directory / "tests" / "config.json").read_text(encoding="utf-8"))
    assert config == {"f2p": task["f2p"], "p2p": task["p2p"]}
    attribution = (directory / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "no upstream" in attribution
    assert "https://github.com" not in attribution
    prepared = prepare_counter(tmp_path / "again")
    assert task["base_commit"] == prepared.sha
