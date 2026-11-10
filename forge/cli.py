"""CLI for license checks, the funnel, patch splits, the sandbox, and outcomes.

Exit status: 0 accepted, a funnel was printed, or a trial was classified.
1 a repository was refused. A finished sandbox uses the container status.
2 the command could not be completed, including a sandbox timeout.
Refusals and funnel counts go to stdout. Failures go to stderr.
"""

from pathlib import Path
from typing import Annotated

import typer

from forge.check import check_repository
from forge.config import find_repo_root, secret_for_redaction
from forge.errors import ForgeError, redact
from forge.funnel import format_report, run_funnel
from forge.gates import format_gates, run_fixture_gates
from forge.models import ReasonCode
from forge.outcomes import format_trial, run_widget_trial
from forge.package import format_package, package_fixture
from forge.sandbox import DEFAULT_TIMEOUT_SECONDS, format_success, run_sandbox
from forge.split import format_split, run_split

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Check licenses, filter pulls, split patches, and run a sandbox."""


@app.command("check")
def check_command(
    repo: Annotated[str, typer.Argument(help="Repository as owner/name.")],
) -> None:
    """Check one repository against the allowlist and the GitHub license."""
    root = find_repo_root()
    try:
        result = check_repository(repo, root=root)
    except Exception as exc:
        _emit_failure(root, exc)
        raise typer.Exit(code=2) from None
    secret = secret_for_redaction(root / ".env")
    if result.accepted:
        if result.spdx_id is None:
            _emit_failure(
                root,
                ForgeError(
                    "Accepted result had no SPDX id.",
                    reason=ReasonCode.INTERNAL,
                ),
            )
            raise typer.Exit(code=2) from None
        typer.echo(redact(f"accepted {result.full_name} spdx={result.spdx_id}", secret))
        return
    reason = result.reason if result.reason is not None else ReasonCode.INTERNAL
    if result.spdx_id is None:
        line = f"refused {result.full_name} reason={reason}"
    else:
        line = f"refused {result.full_name} reason={reason} spdx={result.spdx_id}"
    typer.echo(redact(line, secret))
    raise typer.Exit(code=1)


@app.command("funnel")
def funnel_command(
    repo: Annotated[str, typer.Argument(help="Repository as owner/name.")],
    limit: Annotated[
        int,
        typer.Option("--limit", help="How many closed PRs to read. This does not cap accepts."),
    ],
) -> None:
    """Read closed pull requests and print one rejection count per reason."""
    root = find_repo_root()
    try:
        outcome = run_funnel(repo, root=root, limit=limit)
    except Exception as exc:
        _emit_failure(root, exc)
        raise typer.Exit(code=2) from None
    secret = secret_for_redaction(root / ".env")
    if outcome.report is None:
        refusal = outcome.refusal
        if refusal is None:
            _emit_failure(
                root,
                ForgeError("Funnel finished without a report.", reason=ReasonCode.INTERNAL),
            )
            raise typer.Exit(code=2) from None
        reason = refusal.reason if refusal.reason is not None else ReasonCode.INTERNAL
        if refusal.spdx_id is None:
            line = f"refused {refusal.full_name} reason={reason}"
        else:
            line = f"refused {refusal.full_name} reason={reason} spdx={refusal.spdx_id}"
        typer.echo(redact(line, secret))
        raise typer.Exit(code=1)
    typer.echo(redact(format_report(outcome.report), secret))


@app.command("split")
def split_command(
    repo: Annotated[str, typer.Argument(help="Repository as owner/name.")],
    number: Annotated[int, typer.Argument(help="Pull request number.")],
) -> None:
    """Split one accepted pull request into a source patch and a test patch."""
    root = find_repo_root()
    try:
        outcome = run_split(repo, number, root=root)
    except Exception as exc:
        _emit_failure(root, exc)
        raise typer.Exit(code=2) from None
    secret = secret_for_redaction(root / ".env")
    if outcome.report is None:
        refusal = outcome.repo_refusal
        if refusal is not None:
            reason = refusal.reason if refusal.reason is not None else ReasonCode.INTERNAL
            if refusal.spdx_id is None:
                line = f"refused {refusal.full_name}#{number} reason={reason}"
            else:
                line = (
                    f"refused {refusal.full_name}#{number} reason={reason} spdx={refusal.spdx_id}"
                )
            typer.echo(redact(line, secret))
            raise typer.Exit(code=1)
        if outcome.filter_reason is None:
            _emit_failure(
                root,
                ForgeError("Split finished without a report.", reason=ReasonCode.INTERNAL),
            )
            raise typer.Exit(code=2) from None
        line = f"refused {repo}#{number} reason={outcome.filter_reason}"
        typer.echo(redact(line, secret))
        raise typer.Exit(code=1)
    typer.echo(redact(format_split(outcome.report), secret))


@app.command("sandbox")
def sandbox_command(
    repo: Annotated[str, typer.Argument(help="Repository as owner/name.")],
    sha: Annotated[str, typer.Argument(help="Full 40-character commit SHA.")],
    command: Annotated[list[str], typer.Argument(help="Command to run inside the container.")],
    patch: Annotated[Path, typer.Option("--patch", help="Patch file mounted read-only at /patch.")],
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Seconds before the run is killed. Default is 60."),
    ] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Run a command in a network-free container for one repository commit."""
    root = find_repo_root()
    try:
        outcome = run_sandbox(
            repo,
            sha,
            command,
            root=root,
            patch=patch,
            timeout=timeout,
        )
    except Exception as exc:
        _emit_failure(root, exc)
        raise typer.Exit(code=2) from None
    secret = secret_for_redaction(root / ".env")
    if outcome.success is None:
        refusal = outcome.refusal
        if refusal is None:
            _emit_failure(
                root,
                ForgeError("Sandbox finished without a result.", reason=ReasonCode.INTERNAL),
            )
            raise typer.Exit(code=2) from None
        reason = refusal.reason if refusal.reason is not None else ReasonCode.INTERNAL
        if refusal.spdx_id is None:
            line = f"refused {refusal.full_name} reason={reason}"
        else:
            line = f"refused {refusal.full_name} reason={reason} spdx={refusal.spdx_id}"
        typer.echo(redact(line, secret))
        raise typer.Exit(code=1)
    typer.echo(redact(format_success(outcome.success), secret))
    stderr = redact(outcome.success.stderr, secret)
    if stderr:
        typer.echo(stderr, err=True, nl=not stderr.endswith("\n"))
    if outcome.success.exit_code != 0:
        raise typer.Exit(code=outcome.success.exit_code)


@app.command("outcomes")
def outcomes_command(
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Seconds before the run is killed. Default is 60."),
    ] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Classify one local fixture. A single run is not a validation gate."""
    root = find_repo_root()
    try:
        report = run_widget_trial(root=root, timeout=timeout)
    except Exception as exc:
        _emit_failure(root, exc)
        raise typer.Exit(code=2) from None
    secret = secret_for_redaction(root / ".env")
    typer.echo(redact(format_trial(report), secret))


@app.command("gates")
def gates_command(
    fixture: Annotated[str, typer.Argument(help="Local fixture: widget or counter.")],
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Seconds before one container is killed. Default is 60."),
    ] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Run gates V1 to V5. The first failure is the only reject reason."""
    root = find_repo_root()
    try:
        report = run_fixture_gates(fixture, root=root, timeout=timeout)
    except Exception as exc:
        _emit_failure(root, exc)
        raise typer.Exit(code=2) from None
    secret = secret_for_redaction(root / ".env")
    typer.echo(redact(format_gates(report), secret))
    if report.reason is not None:
        raise typer.Exit(code=1)


@app.command("package")
def package_command(
    fixture: Annotated[str, typer.Argument(help="Local fixture: widget or counter.")],
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Seconds before one container is killed. Default is 60."),
    ] = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Package a fixture the gates accept. A rejection writes nothing."""
    root = find_repo_root()
    try:
        result = package_fixture(fixture, root=root, timeout=timeout)
    except Exception as exc:
        _emit_failure(root, exc)
        raise typer.Exit(code=2) from None
    secret = secret_for_redaction(root / ".env")
    typer.echo(redact(format_package(result), secret))
    if not result.written:
        raise typer.Exit(code=1)


def _emit_failure(root: Path, exc: Exception) -> None:
    secret = secret_for_redaction(root / ".env")
    if isinstance(exc, ForgeError):
        reason = exc.reason
        message = str(exc)
    else:
        reason = ReasonCode.INTERNAL
        message = str(exc)
    typer.echo(f"error reason={reason} {redact(message, secret)}", err=True)
