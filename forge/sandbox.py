"""Run one command in a per-commit image with the network turned off.

The allowlist and the license are checked before any clone or docker build.
The clone lives under data/ and is never executed on the host. The image tag
contains the owner, the name, and the full commit SHA. A run has no network,
a memory limit, a CPU limit, and a timeout. The only host mount is one patch
file at /patch, or one directory of patches at /patches, and it is read-only.
The container filesystem stays writable.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from forge.check import check_repository
from forge.config import secret_for_redaction
from forge.errors import ForgeError
from forge.github import GitHubClient
from forge.models import CheckResult, ReasonCode

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MEMORY = "512m"
DEFAULT_CPUS = "1"
BASE_IMAGE = (
    "python:3.11-slim"
    "@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535"
)
PATCH_TARGET = "/patch"
PATCHES_TARGET = "/patches"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SECRET_KEYS = frozenset({"GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"})


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandTimeout(Exception):
    """A subprocess exceeded the timeout the runner gave it."""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"Command timed out after {timeout} seconds.")
        self.timeout = timeout


Executor = Callable[[list[str], Mapping[str, str], float | None], CommandResult]


@dataclass(frozen=True)
class SandboxSuccess:
    full_name: str
    sha: str
    image: str
    name: str
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class OpenedSandbox:
    full_name: str
    sha: str
    image: str
    name: str


@dataclass(frozen=True)
class SandboxRun:
    refusal: CheckResult | None = None
    success: SandboxSuccess | None = None


def image_tag(owner: str, name: str, sha: str) -> str:
    """Tag that includes the owner, the name, and the full 40-character SHA."""
    digest = _require_sha(sha)
    return f"taskforge/{owner.lower()}/{name.lower()}:{digest}"


def clone_dir(root: Path, owner: str, name: str) -> Path:
    return root / "data" / "clones" / owner / name


def dockerfile_text() -> str:
    """Image contents are the checkout. Nothing from the repository is executed."""
    return f"FROM {BASE_IMAGE}\nWORKDIR /repo\nCOPY . /repo\n"


def eval_dockerfile_text(*, install_checkout: bool = False) -> str:
    """Install git and pytest at build time. The run itself stays offline.

    When ``install_checkout`` is true, ``pip install -e .`` runs after the copy.
    That command installs the checkout and the dependencies its packaging
    file declares. It does not name any other package.
    """
    text = (
        f"FROM {BASE_IMAGE}\n"
        "RUN apt-get update \\\n"
        " && apt-get install -y --no-install-recommends git \\\n"
        " && rm -rf /var/lib/apt/lists/* \\\n"
        " && pip install --no-cache-dir pytest\n"
        "WORKDIR /repo\n"
        "COPY . /repo\n"
    )
    if install_checkout:
        text += "RUN pip install --no-cache-dir -e .\n"
    return text


def checkout_has_packaging(checkout: Path) -> bool:
    """True when the checkout declares a package with pyproject.toml or setup.py."""
    return (checkout / "pyproject.toml").is_file() or (checkout / "setup.py").is_file()


def container_run_args(
    *,
    image: str,
    name: str,
    command: list[str],
    patch: Path,
    memory: str = DEFAULT_MEMORY,
    cpus: str = DEFAULT_CPUS,
) -> list[str]:
    """Arguments for docker run. The container filesystem is not read-only."""
    target = PATCHES_TARGET if patch.is_dir() else PATCH_TARGET
    mount = f"type=bind,source={patch},target={target},readonly"
    return [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--network",
        "none",
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--mount",
        mount,
        image,
        *command,
    ]


def scrub_env(source: Mapping[str, str], secret: str) -> dict[str, str]:
    """Drop the GitHub token so git and docker never receive it."""
    cleaned: dict[str, str] = {}
    for key, value in source.items():
        if key.upper() in _SECRET_KEYS:
            continue
        if secret and (secret in key or secret in value):
            continue
        cleaned[key] = value
    return cleaned


def docker_platform() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "linux/arm64"
    if machine in {"x86_64", "amd64"}:
        return "linux/amd64"
    raise ForgeError(
        f"Unsupported machine architecture {platform.machine()}.",
        reason=ReasonCode.SANDBOX_ERROR,
    )


def run_sandbox(
    repo: str,
    sha: str,
    command: list[str],
    *,
    root: Path,
    patch: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    client: GitHubClient | None = None,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
    host_platform: str | None = None,
) -> SandboxRun:
    """Check, clone, build if needed, run, then remove the container."""
    if timeout < 1:
        raise ForgeError(
            "timeout must be at least 1 second.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    opened = open_sandbox(
        repo,
        sha,
        command,
        root=root,
        patch=patch,
        client=client,
        executor=executor,
        base_env=base_env,
        host_platform=host_platform,
    )
    if isinstance(opened, SandboxRun):
        return opened
    env = _prepared_env(root, base_env)
    run = executor if executor is not None else default_executor
    return _finish(opened, timeout, run, env)


def open_sandbox(
    repo: str,
    sha: str,
    command: list[str],
    *,
    root: Path,
    patch: Path,
    client: GitHubClient | None = None,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
    host_platform: str | None = None,
) -> OpenedSandbox | SandboxRun:
    """Start a detached container. The caller removes it with close_sandbox."""
    if not command:
        raise ForgeError(
            "A sandbox command is required.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    digest = _require_sha(sha)
    gate = check_repository(repo, root=root, client=client)
    if not gate.accepted:
        return SandboxRun(refusal=gate)
    owner, name = gate.full_name.split("/", maxsplit=1)
    patch_path = _validate_patch(patch, root, clone_dir(root, owner, name))
    env = _prepared_env(root, base_env)
    run = executor if executor is not None else default_executor
    secret = secret_for_redaction(root / ".env")
    _reject_secret(command, env, secret)
    checkout = _checkout(owner, name, digest, root, run, env)
    platform_name = host_platform if host_platform is not None else docker_platform()
    _require_base_image(platform_name, run, env)
    tag = image_tag(owner, name, digest)
    _build_image(tag, checkout, root, run, env)
    container = _container_name(digest)
    args = container_run_args(
        image=tag,
        name=container,
        command=command,
        patch=patch_path,
    )
    _reject_secret(args, env, secret)
    started = run(args, env, 120)
    if started.returncode != 0:
        _remove_container(run, container, env, ignore_error=True)
        detail = _one_line(started.stderr or started.stdout)
        raise ForgeError(
            f"docker run failed.{detail}",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    return OpenedSandbox(
        full_name=gate.full_name,
        sha=digest,
        image=tag,
        name=container,
    )


def build_eval_image(
    owner: str,
    name: str,
    sha: str,
    checkout: Path,
    *,
    root: Path,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
    host_platform: str | None = None,
) -> str:
    """Build the eval image. The build may use the network. The run stays offline.

    A checkout with ``pyproject.toml`` or ``setup.py`` is installed with
    ``pip install -e .`` after the files are copied. A checkout without that
    metadata keeps the git and pytest image.
    """
    digest = _require_sha(sha)
    env = _prepared_env(root, base_env)
    run = executor if executor is not None else default_executor
    secret = secret_for_redaction(root / ".env")
    _reject_secret([], env, secret)
    platform_name = host_platform if host_platform is not None else docker_platform()
    _require_base_image(platform_name, run, env)
    tag = image_tag(owner, name, digest)
    _build_image(
        tag,
        checkout,
        root,
        run,
        env,
        text=eval_dockerfile_text(install_checkout=checkout_has_packaging(checkout)),
        filename="eval.Dockerfile",
    )
    return tag


def run_mounted(
    *,
    full_name: str,
    sha: str,
    image: str,
    command: list[str],
    mount: Path,
    checkout: Path,
    root: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
) -> SandboxSuccess:
    """Run one command. The only host mount is ``mount``, and it is read-only."""
    if timeout < 1:
        raise ForgeError(
            "timeout must be at least 1 second.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if not command:
        raise ForgeError(
            "A sandbox command is required.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    digest = _require_sha(sha)
    mount_path = _validate_mount(mount, root, checkout)
    env = _prepared_env(root, base_env)
    run = executor if executor is not None else default_executor
    secret = secret_for_redaction(root / ".env")
    _reject_secret(command, env, secret)
    container = _container_name(digest)
    args = container_run_args(
        image=image,
        name=container,
        command=command,
        patch=mount_path,
    )
    _reject_secret(args, env, secret)
    started = run(args, env, 120)
    if started.returncode != 0:
        _remove_container(run, container, env, ignore_error=True)
        detail = _one_line(started.stderr or started.stdout)
        raise ForgeError(
            f"docker run failed.{detail}",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    opened = OpenedSandbox(
        full_name=full_name,
        sha=digest,
        image=image,
        name=container,
    )
    outcome = _finish(opened, timeout, run, env)
    if outcome.success is None:
        raise ForgeError(
            "Sandbox finished without a result.",
            reason=ReasonCode.INTERNAL,
        )
    return outcome.success


def close_sandbox(
    name: str,
    *,
    root: Path,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
) -> None:
    env = _prepared_env(root, base_env)
    run = executor if executor is not None else default_executor
    _remove_container(run, name, env, ignore_error=False)


def format_success(result: SandboxSuccess) -> str:
    lines = [
        f"repo {result.full_name}",
        f"commit {result.sha}",
        f"image {result.image}",
        f"exit {result.exit_code}",
    ]
    stdout = result.stdout.rstrip("\n")
    if stdout:
        lines.append(stdout)
    return "\n".join(lines)


def default_executor(
    args: list[str],
    env: Mapping[str, str],
    timeout: float | None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            env=dict(env),
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise CommandTimeout(timeout if timeout is not None else 0) from None
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _prepared_env(root: Path, base_env: Mapping[str, str] | None) -> dict[str, str]:
    secret = secret_for_redaction(root / ".env")
    source = base_env if base_env is not None else os.environ
    cleaned = scrub_env(source, secret)
    cleaned["GIT_TERMINAL_PROMPT"] = "0"
    return cleaned


def _require_sha(sha: str) -> str:
    digest = sha.strip().lower()
    if _SHA.fullmatch(digest) is None:
        raise ForgeError(
            "Commit must be a full 40-character SHA.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    return digest


def _validate_patch(patch: Path, root: Path, checkout: Path) -> Path:
    if not patch.is_file():
        raise ForgeError(
            "Patch path must be an existing file.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    resolved = patch.resolve()
    env_file = (root / ".env").resolve()
    checkout_resolved = checkout.resolve()
    if resolved == env_file or resolved.name == ".env":
        raise ForgeError(
            "Refusing to mount .env into the sandbox.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if "docker.sock" in resolved.name or "docker.sock" in str(resolved):
        raise ForgeError(
            "Refusing to mount the docker socket.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if resolved == checkout_resolved or checkout_resolved in resolved.parents:
        raise ForgeError(
            "Refusing to mount the host checkout.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if "," in str(resolved):
        raise ForgeError(
            "Patch path must not contain a comma.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    return resolved


def _validate_mount(path: Path, root: Path, checkout: Path) -> Path:
    if not path.exists() or path.is_symlink():
        raise ForgeError(
            "Mount path must be an existing file or directory.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if not path.is_file() and not path.is_dir():
        raise ForgeError(
            "Mount path must be an existing file or directory.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    resolved = path.resolve()
    env_file = (root / ".env").resolve()
    checkout_resolved = checkout.resolve()
    if resolved == env_file or resolved.name == ".env":
        raise ForgeError(
            "Refusing to mount .env into the sandbox.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if "docker.sock" in resolved.name or "docker.sock" in str(resolved):
        raise ForgeError(
            "Refusing to mount the docker socket.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    inside_checkout = resolved == checkout_resolved or checkout_resolved in resolved.parents
    covers_checkout = resolved in checkout_resolved.parents
    if inside_checkout or covers_checkout:
        raise ForgeError(
            "Refusing to mount the host checkout.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if "," in str(resolved):
        raise ForgeError(
            "Mount path must not contain a comma.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    return resolved


def _checkout(
    owner: str,
    name: str,
    sha: str,
    root: Path,
    run: Executor,
    env: Mapping[str, str],
) -> Path:
    dest = clone_dir(root, owner, name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{owner}/{name}.git"
    if not dest.exists():
        cloned = run(
            [
                "git",
                "-c",
                "credential.helper=",
                "clone",
                "--no-tags",
                url,
                str(dest),
            ],
            env,
            300,
        )
        if cloned.returncode != 0:
            raise ForgeError(
                "git clone failed.",
                reason=ReasonCode.SANDBOX_ERROR,
            )
    else:
        _require_origin(dest, url, run, env)
        fetched = run(
            ["git", "-C", str(dest), "-c", "credential.helper=", "fetch", "origin"],
            env,
            300,
        )
        if fetched.returncode != 0:
            raise ForgeError(
                "git fetch failed.",
                reason=ReasonCode.SANDBOX_ERROR,
            )
    checked = run(["git", "-C", str(dest), "checkout", "--detach", sha], env, 120)
    if checked.returncode != 0:
        raise ForgeError(
            "git checkout of that commit failed.",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    reset = run(["git", "-C", str(dest), "reset", "--hard", sha], env, 120)
    if reset.returncode != 0:
        raise ForgeError(
            "git reset of that commit failed.",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    cleaned = run(["git", "-C", str(dest), "clean", "-fd"], env, 120)
    if cleaned.returncode != 0:
        raise ForgeError(
            "git clean failed.",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    head = run(["git", "-C", str(dest), "rev-parse", "HEAD"], env, 30)
    if head.returncode != 0 or head.stdout.strip().lower() != sha:
        raise ForgeError(
            "Checkout HEAD does not match the requested commit.",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    status = run(["git", "-C", str(dest), "status", "--porcelain"], env, 30)
    if status.returncode != 0 or status.stdout.strip() != "":
        raise ForgeError(
            "Checkout is not a clean tree at the requested commit.",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    return dest


def _require_origin(dest: Path, url: str, run: Executor, env: Mapping[str, str]) -> None:
    """Refuse a clone whose origin is not the GitHub URL for this repository."""
    found = run(["git", "-C", str(dest), "remote", "get-url", "origin"], env, 30)
    if found.returncode != 0 or found.stdout.strip() != url:
        raise ForgeError(
            "Clone origin is not the GitHub URL for this repository.",
            reason=ReasonCode.SANDBOX_ERROR,
        )


def _require_base_image(host_platform: str, run: Executor, env: Mapping[str, str]) -> None:
    inspected = run(
        ["docker", "buildx", "imagetools", "inspect", BASE_IMAGE],
        env,
        60,
    )
    if inspected.returncode != 0:
        raise ForgeError(
            f"Could not inspect {BASE_IMAGE}. Refusing to switch to --platform linux/amd64.",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    if host_platform not in inspected.stdout:
        raise ForgeError(
            f"{BASE_IMAGE} has no {host_platform} build. "
            "Refusing to switch to --platform linux/amd64.",
            reason=ReasonCode.SANDBOX_ERROR,
        )


def _finish(
    opened: OpenedSandbox,
    timeout: float,
    run: Executor,
    env: Mapping[str, str],
) -> SandboxRun:
    try:
        try:
            waited = run(["docker", "wait", opened.name], env, timeout)
        except CommandTimeout:
            _remove_container(run, opened.name, env, ignore_error=False)
            raise ForgeError(
                f"Sandbox run timed out after {timeout:g} seconds. "
                f"Removed container {opened.name}.",
                reason=ReasonCode.SANDBOX_TIMEOUT,
            ) from None
        if waited.returncode != 0:
            raise ForgeError(
                "docker wait failed.",
                reason=ReasonCode.SANDBOX_ERROR,
            )
        logs = run(["docker", "logs", opened.name], env, 60)
        exit_code = _exit_code(waited.stdout)
        return SandboxRun(
            success=SandboxSuccess(
                full_name=opened.full_name,
                sha=opened.sha,
                image=opened.image,
                name=opened.name,
                exit_code=exit_code,
                stdout=logs.stdout,
                stderr=logs.stderr,
            )
        )
    finally:
        _remove_container(run, opened.name, env, ignore_error=True)


def _build_image(
    tag: str,
    checkout: Path,
    root: Path,
    run: Executor,
    env: Mapping[str, str],
    *,
    text: str | None = None,
    filename: str = "Dockerfile",
) -> None:
    dockerfile = root / "data" / "sandbox" / filename
    dockerfile.parent.mkdir(parents=True, exist_ok=True)
    body = dockerfile_text() if text is None else text
    dockerfile.write_text(body, encoding="utf-8")
    built = run(
        [
            "docker",
            "build",
            "--file",
            str(dockerfile),
            "--tag",
            tag,
            str(checkout),
        ],
        env,
        600,
    )
    if built.returncode != 0:
        raise ForgeError(
            "docker build failed.",
            reason=ReasonCode.SANDBOX_ERROR,
        )


def _container_name(sha: str) -> str:
    return f"taskforge-{sha[:12]}-{uuid.uuid4().hex[:8]}"


def _remove_container(
    run: Executor,
    name: str,
    env: Mapping[str, str],
    *,
    ignore_error: bool,
) -> None:
    removed = run(["docker", "rm", "-f", name], env, 60)
    if removed.returncode != 0 and not ignore_error:
        raise ForgeError(
            f"Could not remove sandbox container {name}.",
            reason=ReasonCode.SANDBOX_ERROR,
        )


def _reject_secret(args: list[str], env: Mapping[str, str], secret: str) -> None:
    if any(key.upper() in _SECRET_KEYS for key in env):
        raise ForgeError(
            "Refusing to pass the GitHub token into docker or git.",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    blob = "\n".join([*args, *env.values()])
    if secret and secret in blob:
        raise ForgeError(
            "Refusing to pass the GitHub token into docker or git.",
            reason=ReasonCode.SANDBOX_ERROR,
        )


def _exit_code(stdout: str) -> int:
    text = stdout.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    raise ForgeError(
        "docker wait did not return an exit code.",
        reason=ReasonCode.SANDBOX_ERROR,
    )


def _one_line(text: str) -> str:
    stripped = text.replace("\n", " ").strip()
    if not stripped:
        return ""
    return f" {stripped[:200]}"
