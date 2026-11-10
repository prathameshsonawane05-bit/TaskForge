"""Classification of two pytest runs. These tests do not call Docker."""

from collections.abc import Mapping
from pathlib import Path

from forge.outcomes import (
    TRIAL_SCRIPT,
    classify,
    parse_pytest_verbose,
    run_widget_trial,
)
from forge.sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    CommandResult,
    build_eval_image,
    dockerfile_text,
    eval_dockerfile_text,
)
from tests.fakes import write_project

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"

BEFORE = """\
tests/test_new.py::test_add FAILED
tests/test_keep.py::test_truth PASSED
tests/test_answer.py::test_answer PASSED
tests/test_still.py::test_still_broken FAILED
tests/test_new.py::test_skipped SKIPPED (not a pass)
FAILED tests/test_new.py::test_add - assert 0 == 2
"""

AFTER = """\
tests/test_new.py::test_add PASSED
tests/test_keep.py::test_truth PASSED
tests/test_answer.py::test_answer FAILED
tests/test_still.py::test_still_broken FAILED
tests/test_new.py::test_skipped SKIPPED (not a pass)
"""

TRANSCRIPT = f"""\
SOLUTION_CHECK:absent
BEFORE_STATUS:1
AFTER_STATUS:1
---BEFORE-STDOUT---
{BEFORE}---BEFORE-STDERR---
---AFTER-STDOUT---
{AFTER}---AFTER-STDERR---
"""


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str], float | None]] = []

    def __call__(
        self,
        args: list[str],
        env: Mapping[str, str],
        timeout: float | None,
    ) -> CommandResult:
        self.calls.append((list(args), dict(env), timeout))
        if args[:2] == ["docker", "wait"]:
            return CommandResult(0, "0\n", "")
        if args[:2] == ["docker", "logs"]:
            return CommandResult(0, TRANSCRIPT, "")
        if args[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            return CommandResult(0, "Platform: linux/arm64/v8\n", "")
        return CommandResult(0, "", "")


def test_known_before_and_after_results() -> None:
    before = {
        "pkg/test_new.py::test_add": "fail",
        "pkg/test_keep.py::test_truth": "pass",
        "pkg/test_answer.py::test_answer": "pass",
        "pkg/test_still.py::test_still_broken": "fail",
        "pkg/test_new.py::test_skipped": "skip",
    }
    after = {
        "pkg/test_new.py::test_add": "pass",
        "pkg/test_keep.py::test_truth": "pass",
        "pkg/test_answer.py::test_answer": "fail",
        "pkg/test_still.py::test_still_broken": "fail",
        "pkg/test_new.py::test_skipped": "skip",
    }
    result = classify(before, after)
    assert result.fail_to_pass == ("pkg/test_new.py::test_add",)
    assert result.pass_to_pass == ("pkg/test_keep.py::test_truth",)
    assert result.still_failing == ("pkg/test_still.py::test_still_broken",)
    assert result.regression == ("pkg/test_answer.py::test_answer",)
    assert result.skipped == ("pkg/test_new.py::test_skipped",)
    total = (
        len(result.fail_to_pass)
        + len(result.pass_to_pass)
        + len(result.still_failing)
        + len(result.regression)
        + len(result.skipped)
    )
    assert total == len(set(before) | set(after))


def test_skip_then_skip_is_not_still_failing() -> None:
    result = classify(
        {"tests/test_new.py::test_skipped": "skip"},
        {"tests/test_new.py::test_skipped": "skip"},
    )
    assert result.pass_to_pass == ()
    assert result.fail_to_pass == ()
    assert result.regression == ()
    assert result.still_failing == ()
    assert result.skipped == ("tests/test_new.py::test_skipped",)


def test_skip_then_pass_is_not_fail_to_pass() -> None:
    result = classify(
        {"pkg/test_new.py::test_skipped": "skip"},
        {"pkg/test_new.py::test_skipped": "pass"},
    )
    assert result.fail_to_pass == ()
    assert result.skipped == ("pkg/test_new.py::test_skipped",)
    assert result.pass_to_pass == ()


def test_summary_line_does_not_override_a_pass() -> None:
    parsed = parse_pytest_verbose(
        "tests/test_keep.py::test_truth PASSED\n"
        "FAILED tests/test_keep.py::test_truth - assert\n"
        "tests/test_new.py::test_skipped SKIPPED (not a pass)\n"
        "tests/test_extra.py::test_xpass XPASS\n"
        "tests/test_extra.py::test_xfail XFAIL\n"
    )
    assert parsed["tests/test_keep.py::test_truth"] == "pass"
    assert parsed["tests/test_new.py::test_skipped"] == "skip"
    assert parsed["tests/test_extra.py::test_xpass"] == "pass"
    assert parsed["tests/test_extra.py::test_xfail"] == "fail"


def test_trial_mounts_only_the_patch_directory(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    recorder = Recorder()
    report = run_widget_trial(
        root=tmp_path,
        executor=recorder,
        base_env={"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN},
        host_platform="linux/arm64",
    )
    assert report.classification.fail_to_pass == ("tests/test_new.py::test_add",)
    assert report.classification.pass_to_pass == ("tests/test_keep.py::test_truth",)
    assert report.classification.still_failing == ("tests/test_still.py::test_still_broken",)
    assert report.classification.regression == ("tests/test_answer.py::test_answer",)
    assert report.classification.skipped == ("tests/test_new.py::test_skipped",)
    counted = (
        len(report.classification.fail_to_pass)
        + len(report.classification.pass_to_pass)
        + len(report.classification.still_failing)
        + len(report.classification.regression)
        + len(report.classification.skipped)
    )
    assert counted == 5
    checkout = tmp_path / "data" / "fixtures" / "widget" / "repo"
    source = (checkout / "widget.py").read_text(encoding="utf-8")
    assert "return left - right" in source
    assert "return left + right" not in source
    patch_path = tmp_path / "data" / "fixtures" / "widget" / "patches" / "solution.patch"
    solution = patch_path.read_text(encoding="utf-8")
    assert "return left + right" in solution
    assert "RUN" not in dockerfile_text()
    assert "pytest" not in dockerfile_text()
    eval_text = eval_dockerfile_text()
    assert "RUN" in eval_text
    assert "pytest" in eval_text
    assert "pip" in eval_text

    run_args = next(
        args for args, _env, _timeout in recorder.calls if args[:2] == ["docker", "run"]
    )
    assert run_args[run_args.index("--network") + 1] == "none"
    assert run_args[run_args.index("--memory") + 1] == "512m"
    assert run_args[run_args.index("--cpus") + 1] == "1"
    assert "--read-only" not in run_args
    assert run_args.count("--mount") == 1
    mount = run_args[run_args.index("--mount") + 1]
    patches = tmp_path / "data" / "fixtures" / "widget" / "patches"
    assert mount.endswith("readonly")
    assert f"source={patches.resolve()}" in mount
    assert "target=/patches" in mount
    assert str(checkout.resolve()) not in mount
    assert ".env" not in mount
    assert "docker.sock" not in mount
    assert TRIAL_SCRIPT in run_args
    image = run_args[run_args.index(report.image)]
    assert image == report.image
    command = run_args[run_args.index(report.image) + 1 :]
    assert command[0] == "sh"
    assert "pytest" in command[-1]
    assert "pip " not in command[-1]

    build = next(args for args, _env, _timeout in recorder.calls if args[1] == "build")
    assert "--platform" not in build
    assert "--network" not in build
    dockerfile = Path(build[build.index("--file") + 1])
    assert dockerfile.name == "eval.Dockerfile"
    written = dockerfile.read_text(encoding="utf-8")
    assert "RUN" in written
    assert "pytest" in written
    wait = next(item for item in recorder.calls if item[0][:2] == ["docker", "wait"])
    assert wait[2] == DEFAULT_TIMEOUT_SECONDS
    for args, env, _timeout in recorder.calls:
        assert args[0] == "docker"
        assert TOKEN not in " ".join(args)
        assert "GITHUB_TOKEN" not in env
        assert all(TOKEN not in value for value in env.values())
    assert "pip install -e ." not in written


def test_packaged_checkout_is_installed_after_copy(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/demo"])
    bare = tmp_path / "bare"
    bare.mkdir()
    packaged = tmp_path / "packaged"
    packaged.mkdir()
    (packaged / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    setup_only = tmp_path / "setup-only"
    setup_only.mkdir()
    (setup_only / "setup.py").write_text(
        "from setuptools import setup\nsetup()\n",
        encoding="utf-8",
    )
    config_only = tmp_path / "config-only"
    config_only.mkdir()
    (config_only / "setup.cfg").write_text("[metadata]\nname = demo\n", encoding="utf-8")
    sha = "a" * 40
    recorder = Recorder()
    env = {"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN}

    bare_tag = build_eval_image(
        "acme",
        "demo",
        sha,
        bare,
        root=tmp_path,
        executor=recorder,
        base_env=env,
        host_platform="linux/arm64",
    )
    bare_text = (tmp_path / "data" / "sandbox" / "eval.Dockerfile").read_text(encoding="utf-8")
    assert bare_tag == f"taskforge/acme/demo:{sha}"
    assert bare_text == eval_dockerfile_text()
    assert "pip install -e ." not in bare_text

    build_eval_image(
        "acme",
        "demo",
        sha,
        packaged,
        root=tmp_path,
        executor=recorder,
        base_env=env,
        host_platform="linux/arm64",
    )
    packaged_text = (tmp_path / "data" / "sandbox" / "eval.Dockerfile").read_text(encoding="utf-8")
    copy_at = packaged_text.index("COPY . /repo")
    install_at = packaged_text.index("RUN pip install --no-cache-dir -e .")
    assert install_at > copy_at
    assert packaged_text.endswith("RUN pip install --no-cache-dir -e .\n")
    assert "pip install click" not in packaged_text
    assert "pip install pytest" not in packaged_text

    build_eval_image(
        "acme",
        "demo",
        sha,
        setup_only,
        root=tmp_path,
        executor=recorder,
        base_env=env,
        host_platform="linux/arm64",
    )
    setup_text = (tmp_path / "data" / "sandbox" / "eval.Dockerfile").read_text(encoding="utf-8")
    assert setup_text.endswith("RUN pip install --no-cache-dir -e .\n")

    build_eval_image(
        "acme",
        "demo",
        sha,
        config_only,
        root=tmp_path,
        executor=recorder,
        base_env=env,
        host_platform="linux/arm64",
    )
    config_text = (tmp_path / "data" / "sandbox" / "eval.Dockerfile").read_text(encoding="utf-8")
    assert config_text == eval_dockerfile_text()
    for args, _env, _timeout in recorder.calls:
        if args[1] == "build":
            assert "--network" not in args
            assert "--platform" not in args
