"""Isolation settings for the sandbox. These tests do not call Docker."""

from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from forge.cli import app
from forge.errors import ForgeError
from forge.models import ReasonCode
from forge.sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    CommandResult,
    CommandTimeout,
    SandboxRun,
    SandboxSuccess,
    image_tag,
    run_sandbox,
)
from tests.fakes import make_client, repository_body, write_project

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"
SHA = "abcdef123456" + "a" * 28
OTHER_SHA = "abcdef123456" + "b" * 28
runner = CliRunner()


class Recorder:
    def __init__(
        self,
        sha: str,
        *,
        fail_wait: bool = False,
        platforms: str = "linux/arm64/v8",
    ) -> None:
        self.sha = sha
        self.fail_wait = fail_wait
        self.platforms = platforms
        self.calls: list[tuple[list[str], dict[str, str], float | None]] = []

    def __call__(
        self,
        args: list[str],
        env: Mapping[str, str],
        timeout: float | None,
    ) -> CommandResult:
        copied = dict(env.items())
        self.calls.append((list(args), copied, timeout))
        if args[:2] == ["docker", "wait"] and self.fail_wait:
            raise CommandTimeout(timeout if timeout is not None else 0)
        if "rev-parse" in args:
            return CommandResult(0, self.sha + "\n", "")
        if args[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            return CommandResult(0, f"Platform: {self.platforms}\n", "")
        if args[:2] == ["docker", "wait"]:
            return CommandResult(0, "0\n", "")
        if args[:2] == ["docker", "logs"]:
            return CommandResult(0, "ok\n", "")
        return CommandResult(0, "", "")


def _patch(tmp_path: Path) -> Path:
    path = tmp_path / "change.patch"
    path.write_text("diff --git a/x b/x\n", encoding="utf-8")
    return path


def _env() -> dict[str, str]:
    return {"PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": TOKEN}


def _args(recorder: Recorder, *parts: str) -> list[str]:
    for args, _env, _timeout in recorder.calls:
        if tuple(args[: len(parts)]) == parts:
            return args
    raise AssertionError(parts)


def _assert_clean(recorder: Recorder) -> None:
    for args, env, _timeout in recorder.calls:
        blob = " ".join(args)
        assert TOKEN not in blob
        assert "GITHUB_TOKEN" not in env
        assert all(TOKEN not in value for value in env.values())
        assert "docker.sock" not in blob


def test_two_commits_do_not_share_a_tag() -> None:
    first = image_tag("Pallets", "Click", SHA)
    second = image_tag("pallets", "click", OTHER_SHA)
    assert first != second
    assert SHA in first
    assert OTHER_SHA not in first
    assert "pallets" in first
    assert "click" in first
    assert len(SHA) == 40
    assert len(OTHER_SHA) == 40
    assert SHA[:12] == OTHER_SHA[:12]


def test_short_sha_is_rejected(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    recorder = Recorder(SHA)
    with pytest.raises(ForgeError) as caught:
        run_sandbox(
            "acme/widgets",
            "abcdef",
            ["true"],
            root=tmp_path,
            patch=_patch(tmp_path),
            executor=recorder,
            base_env=_env(),
            host_platform="linux/arm64",
        )
    assert caught.value.reason == ReasonCode.CONFIG_ERROR
    assert recorder.calls == []


def test_unlisted_repo_does_not_reach_docker(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])

    def fail(_args: list[str], _env: Mapping[str, str], _timeout: float | None) -> CommandResult:
        raise AssertionError("docker or git was called")

    outcome = run_sandbox(
        "torvalds/linux",
        SHA,
        ["true"],
        root=tmp_path,
        patch=tmp_path / "missing.patch",
        executor=fail,
        base_env=_env(),
        host_platform="linux/arm64",
    )
    assert outcome.refusal is not None
    assert outcome.refusal.reason == ReasonCode.NOT_ON_ALLOWLIST


def test_rejected_license_does_not_reach_docker(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=repository_body("acme/widgets", "GPL-3.0"))

    def fail(_args: list[str], _env: Mapping[str, str], _timeout: float | None) -> CommandResult:
        raise AssertionError("docker or git was called")

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        outcome = run_sandbox(
            "acme/widgets",
            SHA,
            ["true"],
            root=tmp_path,
            patch=_patch(tmp_path),
            client=client,
            executor=fail,
            base_env=_env(),
            host_platform="linux/arm64",
        )
    assert outcome.refusal is not None
    assert outcome.refusal.reason == ReasonCode.LICENSE_NOT_ALLOWED


def test_run_args_are_isolated_and_hide_the_token(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    recorder = Recorder(SHA)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))

    patch = _patch(tmp_path)
    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        outcome = run_sandbox(
            "acme/widgets",
            SHA,
            ["true"],
            root=tmp_path,
            patch=patch,
            client=client,
            executor=recorder,
            base_env=_env(),
            host_platform="linux/arm64",
        )
    assert outcome.success is not None
    assert outcome.success.exit_code == 0
    assert outcome.success.image == image_tag("acme", "widgets", SHA)
    _assert_clean(recorder)

    run_args = _args(recorder, "docker", "run")
    assert run_args[run_args.index("--network") + 1] == "none"
    assert run_args[run_args.index("--memory") + 1] == "512m"
    assert run_args[run_args.index("--cpus") + 1] == "1"
    assert "--read-only" not in run_args
    assert "-v" not in run_args
    assert run_args.count("--mount") == 1
    mount = run_args[run_args.index("--mount") + 1]
    assert "readonly" in mount
    assert str(patch.resolve()) in mount
    assert mount.endswith("readonly")
    clone = tmp_path / "data" / "clones" / "acme" / "widgets"
    assert str(clone) not in mount
    assert ".env" not in " ".join(run_args)

    build = next(args for args, _env, _timeout in recorder.calls if args[1] == "build")
    assert "--platform" not in build
    assert "--network" not in build
    assert SHA in " ".join(build)
    dockerfile = Path(build[build.index("--file") + 1])
    assert clone.resolve() not in dockerfile.resolve().parents
    assert build[-1] == str(clone)
    text = dockerfile.read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in text
    assert "COPY . /repo" in text
    assert "RUN" not in text
    assert "pytest" not in text
    assert "pip" not in text

    clone_cmd = next(args for args, _env, _timeout in recorder.calls if "clone" in args)
    assert "credential.helper=" in clone_cmd
    assert clone_cmd[-2] == "https://github.com/acme/widgets.git"
    assert clone_cmd[-1] == str(clone)
    banned = {"pytest", "pip", "setup.py"}
    for args, env, _timeout in recorder.calls:
        assert args[0] in {"git", "docker"}
        assert banned.isdisjoint(args)
        assert TOKEN not in env.get("GITHUB_TOKEN", "")

    wait = next(item for item in recorder.calls if item[0][:2] == ["docker", "wait"])
    assert wait[2] is not None
    assert wait[2] >= 60
    assert wait[2] == DEFAULT_TIMEOUT_SECONDS
    name = run_args[run_args.index("--name") + 1]
    assert any(args == ["docker", "rm", "-f", name] for args, _env, _timeout in recorder.calls)


def test_timeout_removes_the_container(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    recorder = Recorder(SHA, fail_wait=True)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        with pytest.raises(ForgeError) as caught:
            run_sandbox(
                "acme/widgets",
                SHA,
                ["sleep", "30"],
                root=tmp_path,
                patch=_patch(tmp_path),
                timeout=3,
                client=client,
                executor=recorder,
                base_env=_env(),
                host_platform="linux/arm64",
            )
    assert caught.value.reason == ReasonCode.SANDBOX_TIMEOUT
    run_args = _args(recorder, "docker", "run")
    name = run_args[run_args.index("--name") + 1]
    wait = next(item for item in recorder.calls if item[0][:2] == ["docker", "wait"])
    assert wait[2] == 3
    assert any(args == ["docker", "rm", "-f", name] for args, _env, _timeout in recorder.calls)
    assert name in str(caught.value)
    _assert_clean(recorder)


def test_missing_arm64_build_does_not_switch_platform(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    recorder = Recorder(SHA, platforms="linux/amd64")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        with pytest.raises(ForgeError) as caught:
            run_sandbox(
                "acme/widgets",
                SHA,
                ["true"],
                root=tmp_path,
                patch=_patch(tmp_path),
                client=client,
                executor=recorder,
                base_env=_env(),
                host_platform="linux/arm64",
            )
    message = str(caught.value)
    assert "Refusing to switch to --platform linux/amd64" in message
    assert not any(args[1] == "build" for args, _env, _timeout in recorder.calls)


def test_cli_refuses_an_unlisted_repo_without_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["sandbox", "torvalds/linux", SHA, "--patch", "change.patch", "true"],
    )
    text = f"{result.stdout}{result.stderr}"
    assert result.exit_code == 1
    assert "refused torvalds/linux reason=not_on_allowlist" in result.stdout
    assert TOKEN not in text


def test_cli_process_status_is_the_container_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)
    seen: dict[str, int] = {}

    def fake_run(*_args: object, **_kwargs: object) -> SandboxRun:
        code = seen["code"]
        return SandboxRun(
            success=SandboxSuccess(
                full_name="acme/widgets",
                sha=SHA,
                image=image_tag("acme", "widgets", SHA),
                name="taskforge-demo",
                exit_code=code,
                stdout="stdout-line\n",
                stderr="stderr-line\n",
            )
        )

    monkeypatch.setattr("forge.cli.run_sandbox", fake_run)
    for code in (1, 2, 0):
        seen["code"] = code
        result = runner.invoke(
            app,
            ["sandbox", "acme/widgets", SHA, "--patch", "change.patch", "true"],
        )
        assert result.exit_code == code
        assert "stdout-line" in result.stdout
        assert f"exit {code}" in result.stdout
        assert "stderr-line" in result.stderr
        assert "sandbox_timeout" not in f"{result.stdout}{result.stderr}"
        assert TOKEN not in f"{result.stdout}{result.stderr}"


def test_cli_timeout_stays_process_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)

    def fake_run(*_args: object, **_kwargs: object) -> SandboxRun:
        raise ForgeError(
            "Sandbox run timed out after 3 seconds. Removed container taskforge-demo.",
            reason=ReasonCode.SANDBOX_TIMEOUT,
        )

    monkeypatch.setattr("forge.cli.run_sandbox", fake_run)
    result = runner.invoke(
        app,
        ["sandbox", "acme/widgets", SHA, "--patch", "change.patch", "sleep", "30"],
    )
    assert result.exit_code == 2
    assert "reason=sandbox_timeout" in result.stderr
    assert "exit 2" not in result.stdout
    assert TOKEN not in f"{result.stdout}{result.stderr}"
