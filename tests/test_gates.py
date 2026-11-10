"""Validation gates. These tests do not call Docker."""

from collections.abc import Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forge.cli import app
from forge.gates import (
    GATE_RUNTIME_LIMIT_SECONDS,
    GateReason,
    GateRun,
    first_reason,
    run_fixture_gates,
)
from forge.outcomes import BASELINE_SCRIPT, SOLVED_SCRIPT, Classification
from forge.sandbox import DEFAULT_TIMEOUT_SECONDS, CommandResult
from tests.fakes import write_project

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"
runner = CliRunner()

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
---BEFORE-STDERR---
---AFTER-STDOUT---
tests/test_new.py::test_add PASSED
tests/test_keep.py::test_truth PASSED
tests/test_answer.py::test_answer FAILED
tests/test_still.py::test_still_broken FAILED
tests/test_new.py::test_skipped SKIPPED (not a pass)
---AFTER-STDERR---
"""

COUNTER_LOG = """\
SOLUTION_CHECK:absent
BEFORE_STATUS:1
AFTER_STATUS:0
---BEFORE-STDOUT---
tests/test_keep.py::test_truth PASSED
tests/test_value.py::test_value FAILED
---BEFORE-STDERR---
---AFTER-STDOUT---
tests/test_keep.py::test_truth PASSED
tests/test_value.py::test_value PASSED
---AFTER-STDERR---
"""


class Recorder:
    def __init__(self, logs: str, *, fail_build: bool = False) -> None:
        self.logs = logs
        self.fail_build = fail_build
        self.calls: list[tuple[list[str], dict[str, str], float | None]] = []

    def __call__(
        self,
        args: list[str],
        env: Mapping[str, str],
        timeout: float | None,
    ) -> CommandResult:
        self.calls.append((list(args), dict(env), timeout))
        if args[:2] == ["docker", "build"] and self.fail_build:
            return CommandResult(1, "", "docker build failed")
        if args[:2] == ["docker", "wait"]:
            return CommandResult(0, "0\n", "")
        if args[:2] == ["docker", "logs"]:
            return CommandResult(0, self.logs, "")
        if args[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            return CommandResult(0, "Platform: linux/arm64/v8\n", "")
        return CommandResult(0, "", "")


def _clean(*, after_status: int = 0, elapsed: float = 0.1, extra_still: str = "") -> GateRun:
    still = (extra_still,) if extra_still else ()
    return GateRun(
        classification=Classification(
            fail_to_pass=("tests/test_value.py::test_value",),
            pass_to_pass=("tests/test_keep.py::test_truth",),
            still_failing=still,
            regression=(),
            skipped=(),
        ),
        before_status=1,
        after_status=after_status,
        failed_before=("tests/test_value.py::test_value",),
        elapsed=elapsed,
    )


def test_runtime_limit_is_written_down() -> None:
    assert GATE_RUNTIME_LIMIT_SECONDS == 30


def test_build_failed_is_the_first_gate() -> None:
    skipped = GateRun(
        classification=Classification((), (), (), (), ("tests/test_new.py::test_skipped",)),
        before_status=0,
        after_status=0,
        failed_before=(),
        elapsed=0.1,
    )
    reason = first_reason((skipped,), build_ok=False, limit_seconds=30)
    assert reason == GateReason.BUILD_FAILED


def test_skip_is_not_a_failure_before() -> None:
    skipped = GateRun(
        classification=Classification((), (), (), (), ("tests/test_new.py::test_skipped",)),
        before_status=0,
        after_status=0,
        failed_before=(),
        elapsed=0.1,
    )
    reason = first_reason((skipped,), build_ok=True, limit_seconds=30)
    assert reason == GateReason.NO_FAILURE_BEFORE


def test_no_fail_to_pass_comes_before_regression() -> None:
    run = GateRun(
        classification=Classification(
            fail_to_pass=(),
            pass_to_pass=(),
            still_failing=("pkg/test_still.py::test_still_broken",),
            regression=("pkg/test_answer.py::test_answer",),
            skipped=(),
        ),
        before_status=1,
        after_status=1,
        failed_before=("pkg/test_still.py::test_still_broken",),
        elapsed=0.1,
    )
    assert first_reason((run,), build_ok=True, limit_seconds=30) == GateReason.NO_FAIL_TO_PASS


def test_widget_shape_is_rejected_for_regression() -> None:
    run = GateRun(
        classification=Classification(
            fail_to_pass=("tests/test_new.py::test_add",),
            pass_to_pass=("tests/test_keep.py::test_truth",),
            still_failing=("tests/test_still.py::test_still_broken",),
            regression=("tests/test_answer.py::test_answer",),
            skipped=("tests/test_new.py::test_skipped",),
        ),
        before_status=1,
        after_status=1,
        failed_before=(
            "tests/test_new.py::test_add",
            "tests/test_still.py::test_still_broken",
        ),
        elapsed=0.2,
    )
    assert first_reason((run,), build_ok=True, limit_seconds=30) == GateReason.REGRESSION


def test_disagreeing_second_run_is_flaky() -> None:
    runs = (_clean(), _clean(after_status=1), _clean())
    assert first_reason(runs, build_ok=True, limit_seconds=30) == GateReason.FLAKY


def test_disagreeing_classification_is_flaky_before_too_slow() -> None:
    runs = (
        _clean(elapsed=20),
        _clean(extra_still="tests/test_other.py::test_other", elapsed=20),
        _clean(elapsed=20),
    )
    assert first_reason(runs, build_ok=True, limit_seconds=30) == GateReason.FLAKY


def test_runtime_over_the_limit_is_too_slow() -> None:
    runs = (_clean(elapsed=10), _clean(elapsed=10), _clean(elapsed=10.1))
    assert first_reason(runs, build_ok=True, limit_seconds=30) == GateReason.TOO_SLOW


def test_runtime_equal_to_the_limit_passes() -> None:
    runs = (_clean(elapsed=10), _clean(elapsed=10), _clean(elapsed=10))
    assert first_reason(runs, build_ok=True, limit_seconds=30) is None


def test_failed_build_does_not_start_a_container(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    recorder = Recorder(WIDGET_LOG, fail_build=True)
    report = run_fixture_gates(
        "widget",
        root=tmp_path,
        executor=recorder,
        base_env={"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN},
        host_platform="linux/arm64",
    )
    assert report.reason == GateReason.BUILD_FAILED
    assert report.runs == ()
    assert not any(args[:2] == ["docker", "run"] for args, _env, _timeout in recorder.calls)
    for args, env, _timeout in recorder.calls:
        assert args[0] == "docker"
        assert TOKEN not in " ".join(args)
        assert "GITHUB_TOKEN" not in env


def test_widget_stops_after_one_baseline_and_one_solved_container(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    recorder = Recorder(WIDGET_LOG)
    report = run_fixture_gates(
        "widget",
        root=tmp_path,
        executor=recorder,
        base_env={"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN},
        host_platform="linux/arm64",
    )
    assert report.reason == GateReason.REGRESSION
    assert len(report.runs) == 1
    assert report.runs[0].classification.regression == ("tests/test_answer.py::test_answer",)
    assert report.runs[0].classification.skipped == ("tests/test_new.py::test_skipped",)
    assert report.runs[0].classification.fail_to_pass == ("tests/test_new.py::test_add",)
    runs = [args for args, _env, _timeout in recorder.calls if args[:2] == ["docker", "run"]]
    assert len(runs) == 2
    assert runs[0][-1] == BASELINE_SCRIPT
    assert runs[1][-1] == SOLVED_SCRIPT


def test_counter_runs_three_fresh_containers(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    recorder = Recorder(COUNTER_LOG)
    report = run_fixture_gates(
        "counter",
        root=tmp_path,
        executor=recorder,
        base_env={"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN},
        host_platform="linux/arm64",
    )
    assert report.reason is None
    assert len(report.runs) == 3
    assert report.limit_seconds == GATE_RUNTIME_LIMIT_SECONDS
    first = report.runs[0].classification
    assert first.fail_to_pass == ("tests/test_value.py::test_value",)
    assert first.pass_to_pass == ("tests/test_keep.py::test_truth",)
    assert first.still_failing == ()
    assert first.regression == ()
    assert first.skipped == ()
    assert all(run.classification == first for run in report.runs)
    assert all(run.before_status == 1 and run.after_status == 0 for run in report.runs)
    assert sum(run.elapsed for run in report.runs) <= report.limit_seconds
    checkout = tmp_path / "data" / "fixtures" / "counter" / "repo"
    assert "return 0" in (checkout / "counter.py").read_text(encoding="utf-8")
    runs = [args for args, _env, _timeout in recorder.calls if args[:2] == ["docker", "run"]]
    assert len(runs) == 6
    names = [args[args.index("--name") + 1] for args in runs]
    assert len(set(names)) == 6
    assert [args[-1] for args in runs] == [
        BASELINE_SCRIPT,
        SOLVED_SCRIPT,
        BASELINE_SCRIPT,
        SOLVED_SCRIPT,
        BASELINE_SCRIPT,
        SOLVED_SCRIPT,
    ]
    assert len({args[args.index(report.image)] for args in runs}) == 1
    builds = [args for args, _env, _timeout in recorder.calls if args[1] == "build"]
    assert len(builds) == 1
    assert "--platform" not in builds[0]
    for args in runs:
        assert args[args.index("--network") + 1] == "none"
        assert args[args.index("--memory") + 1] == "512m"
        assert args[args.index("--cpus") + 1] == "1"
        assert args.count("--mount") == 1
        mount = args[args.index("--mount") + 1]
        assert mount.endswith("readonly")
        assert "target=/patches" in mount
        assert str(checkout.resolve()) not in mount
    waits = [item for item in recorder.calls if item[0][:2] == ["docker", "wait"]]
    assert len(waits) == 6
    assert all(item[2] == DEFAULT_TIMEOUT_SECONDS for item in waits)


def test_cli_rejection_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)
    from forge.gates import GateReport

    report = GateReport(
        full_name="local/widget",
        sha="a" * 40,
        image="taskforge/local/widget:" + "a" * 40,
        reason=GateReason.REGRESSION,
        runs=(
            GateRun(
                classification=Classification(
                    ("tests/test_new.py::test_add",),
                    ("tests/test_keep.py::test_truth",),
                    ("tests/test_still.py::test_still_broken",),
                    ("tests/test_answer.py::test_answer",),
                    ("tests/test_new.py::test_skipped",),
                ),
                before_status=1,
                after_status=1,
                failed_before=("tests/test_new.py::test_add",),
                elapsed=0.2,
            ),
        ),
        limit_seconds=30,
    )
    monkeypatch.setattr("forge.cli.run_fixture_gates", lambda *_args, **_kwargs: report)
    result = runner.invoke(app, ["gates", "widget"])
    assert result.exit_code == 1
    assert "rejected regression" in result.stdout
    assert "tests/test_answer.py::test_answer" in result.stdout
    assert TOKEN not in result.stdout
