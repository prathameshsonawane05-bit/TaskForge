"""Classification of two pytest runs. These tests do not call Docker."""

import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from forge.errors import ForgeError
from forge.models import ReasonCode
from forge.outcomes import (
    BASELINE_SCRIPT,
    SOLVED_SCRIPT,
    classify,
    format_trial,
    parse_pytest_verbose,
    run_trial_container,
    run_widget_trial,
)
from forge.sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    OFFLINE_EDITABLE_INSTALL,
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

    runs = [args for args, _env, _timeout in recorder.calls if args[:2] == ["docker", "run"]]
    assert len(runs) == 2
    patches = tmp_path / "data" / "fixtures" / "widget" / "patches"
    assert runs[0][-1] == BASELINE_SCRIPT
    assert runs[1][-1] == SOLVED_SCRIPT
    assert "apply /patches/solution.patch" not in BASELINE_SCRIPT
    assert "apply --check /patches/solution.patch" in BASELINE_SCRIPT
    assert BASELINE_SCRIPT.index("apply /patches/test.patch") < BASELINE_SCRIPT.index("pytest")
    solved_test = SOLVED_SCRIPT.index("apply /patches/test.patch")
    solved_solution = SOLVED_SCRIPT.index("apply /patches/solution.patch")
    assert solved_test < solved_solution < SOLVED_SCRIPT.index("pytest")
    names = []
    for run_args in runs:
        assert run_args[run_args.index("--network") + 1] == "none"
        assert run_args[run_args.index("--memory") + 1] == "512m"
        assert run_args[run_args.index("--cpus") + 1] == "1"
        assert "--read-only" not in run_args
        assert run_args.count("--mount") == 1
        mount = run_args[run_args.index("--mount") + 1]
        assert mount.endswith("readonly")
        assert f"source={patches.resolve()}" in mount
        assert "target=/patches" in mount
        assert str(checkout.resolve()) not in mount
        assert ".env" not in mount
        assert "docker.sock" not in mount
        assert run_args[run_args.index(report.image)] == report.image
        command = run_args[run_args.index(report.image) + 1 :]
        assert command[0] == "sh"
        assert "pytest" in command[-1]
        assert "pip " not in command[-1]
        names.append(run_args[run_args.index("--name") + 1])
    assert names[0] != names[1]
    sequence: list[tuple[str, str]] = []
    for args, _env, _timeout in recorder.calls:
        if args[:2] == ["docker", "run"]:
            sequence.append(("run", args[args.index("--name") + 1]))
        elif args[:3] == ["docker", "rm", "-f"]:
            sequence.append(("rm", args[-1]))
    assert sequence.index(("rm", names[0])) < sequence.index(("run", names[1]))

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
    formatted = format_trial(report)
    assert "solution_absent yes" in formatted.splitlines()
    without = format_trial(replace(report, trial_stdout="BEFORE_STATUS:1\n"))
    assert "solution_absent no" in without.splitlines()
    assert "solution_absent yes" not in without.splitlines()


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
    install_at = packaged_text.index(OFFLINE_EDITABLE_INSTALL)
    assert install_at > copy_at
    assert packaged_text.endswith(OFFLINE_EDITABLE_INSTALL + "\n")
    assert "pip install click" not in packaged_text
    assert "pip install pytest" not in packaged_text
    assert "--network=none" in packaged_text
    assert "RUN pip install --no-cache-dir -e ." not in packaged_text

    builds_before = sum(
        1 for args, _env, _timeout in recorder.calls if len(args) > 1 and args[1] == "build"
    )
    try:
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
    except ForgeError as exc:
        setup_error = exc
    else:
        raise AssertionError("setup.py without static dependencies was installed")
    assert setup_error.reason is ReasonCode.SANDBOX_ERROR
    builds_after = sum(
        1 for args, _env, _timeout in recorder.calls if len(args) > 1 and args[1] == "build"
    )
    assert builds_after == builds_before
    setup_text = (tmp_path / "data" / "sandbox" / "eval.Dockerfile").read_text(encoding="utf-8")
    assert setup_text == packaged_text
    assert not setup_text.endswith("RUN pip install --no-cache-dir -e .\n")

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


def test_static_names_are_installed_before_the_offline_line(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/demo"])
    checkout = tmp_path / "named"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text(
        "\n".join(
            [
                "[build-system]",
                'requires = ["setuptools>=68"]',
                'build-backend = "setuptools.build_meta"',
                "",
                "[project]",
                'name = "demo"',
                'version = "0.1.0"',
                'dependencies = ["packaging>=21", "httpx[http2]>=0.27"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    dynamic = tmp_path / "dynamic"
    dynamic.mkdir()
    (dynamic / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "demo"',
                'version = "0.1.0"',
                'dynamic = ["dependencies"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    sha = "b" * 40
    recorder = Recorder()
    env = {"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN}
    build_eval_image(
        "acme",
        "demo",
        sha,
        checkout,
        root=tmp_path,
        executor=recorder,
        base_env=env,
        host_platform="linux/arm64",
    )
    text = (tmp_path / "data" / "sandbox" / "eval.Dockerfile").read_text(encoding="utf-8")
    prefetch = "RUN pip install --no-cache-dir setuptools packaging httpx"
    copy_at = text.index("COPY . /repo")
    assert text.index(prefetch) < copy_at
    assert copy_at < text.index(OFFLINE_EDITABLE_INSTALL)
    assert text.endswith(OFFLINE_EDITABLE_INSTALL + "\n")
    offline_line = text.splitlines()[-1]
    assert offline_line == OFFLINE_EDITABLE_INSTALL
    assert "packaging" not in offline_line
    assert "httpx" not in offline_line
    assert "click" not in text
    assert "pip install click" not in text
    builds_before = sum(
        1 for args, _env, _timeout in recorder.calls if len(args) > 1 and args[1] == "build"
    )
    try:
        build_eval_image(
            "acme",
            "demo",
            sha,
            dynamic,
            root=tmp_path,
            executor=recorder,
            base_env=env,
            host_platform="linux/arm64",
        )
    except ForgeError as exc:
        dynamic_error = exc
    else:
        raise AssertionError("a dynamic dependency table was installed")
    assert dynamic_error.reason is ReasonCode.SANDBOX_ERROR
    builds_after = sum(
        1 for args, _env, _timeout in recorder.calls if len(args) > 1 and args[1] == "build"
    )
    assert builds_after == builds_before
    assert (tmp_path / "data" / "sandbox" / "eval.Dockerfile").read_text(encoding="utf-8") == text


class _FreshTree:
    """One docker run gets one copy of the fixture. A second run starts clean."""

    def __init__(self, source: Path, patches: Path, work: Path) -> None:
        self.source = source
        self.patches = patches
        self.work = work
        self.trees: list[Path] = []
        self.leak_at_start: list[bool] = []
        self._outputs: dict[str, subprocess.CompletedProcess[str]] = {}

    def __call__(
        self,
        args: list[str],
        env: Mapping[str, str],
        timeout: float | None,
    ) -> CommandResult:
        if args[:2] == ["docker", "run"]:
            name = args[args.index("--name") + 1]
            dest = self.work / name
            shutil.copytree(self.source, dest)
            self.trees.append(dest)
            self.leak_at_start.append((dest / "leak.txt").exists())
            private = dest / "trial-out"
            private.mkdir()
            script = args[-1]
            rewritten = (
                script.replace("/tmp/before.txt", str(private / "before.txt"))
                .replace("/tmp/before.err", str(private / "before.err"))
                .replace("/tmp/after.txt", str(private / "after.txt"))
                .replace("/tmp/after.err", str(private / "after.err"))
                .replace("/patches", str(self.patches))
                .replace("/repo", str(dest))
            )
            self._outputs[name] = subprocess.run(
                ["sh", "-c", rewritten],
                env=dict(env),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return CommandResult(0, "", "")
        if args[:2] == ["docker", "wait"]:
            code = self._outputs[args[2]].returncode
            return CommandResult(0, f"{code}\n", "")
        if args[:2] == ["docker", "logs"]:
            completed = self._outputs[args[2]]
            return CommandResult(0, completed.stdout, completed.stderr)
        return CommandResult(0, "", "")


def test_solved_pytest_starts_without_a_file_the_baseline_created(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("def value():\n    return 0\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    test_text = (
        "from pathlib import Path\n\n"
        "import app\n\n\n"
        "def test_value():\n"
        '    leak = Path("leak.txt")\n'
        "    if leak.exists():\n"
        '        raise AssertionError("baseline residue")\n'
        '    leak.write_text("created\\n")\n'
        "    assert app.value() == 1\n"
    )
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "solution.patch").write_text(
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def value():\n"
        "-    return 0\n"
        "+    return 1\n",
        encoding="utf-8",
    )
    body = "".join(f"+{line}\n" for line in test_text.splitlines())
    count = len(test_text.splitlines())
    (patches / "test.patch").write_text(
        "diff --git a/tests/test_value.py b/tests/test_value.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/tests/test_value.py\n"
        f"@@ -0,0 +1,{count} @@\n"
        f"{body}",
        encoding="utf-8",
    )
    runner = _FreshTree(source, patches, tmp_path / "runs")
    path = f"{Path(sys.executable).parent}:/usr/bin:/bin"
    report = run_trial_container(
        full_name="local/leak",
        sha="a" * 40,
        image="taskforge/local/leak:" + ("a" * 40),
        patches=patches,
        checkout=source,
        root=tmp_path,
        executor=runner,
        base_env={"PATH": path, "HOME": str(tmp_path), "GITHUB_TOKEN": TOKEN},
    )
    assert runner.leak_at_start == [False, False]
    assert len(set(runner.trees)) == 2
    assert (runner.trees[0] / "leak.txt").is_file()
    assert not (source / "leak.txt").exists()
    assert report.classification.fail_to_pass == ("tests/test_value.py::test_value",)
    assert report.classification.pass_to_pass == ()
    assert report.classification.still_failing == ()
    assert TOKEN not in report.trial_stdout
