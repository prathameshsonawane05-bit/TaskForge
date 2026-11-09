"""CLI for one-repository allowlist and license checks.

Exit status: 0 accepted, 1 refused, 2 the check could not be completed.
Refusals are printed to stdout. Failures are printed to stderr.
"""

from pathlib import Path
from typing import Annotated

import typer

from forge.check import check_repository
from forge.config import find_repo_root, secret_for_redaction
from forge.errors import ForgeError, redact
from forge.models import ReasonCode

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Check allowlisted public repositories and confirm SPDX licenses."""


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


def _emit_failure(root: Path, exc: Exception) -> None:
    secret = secret_for_redaction(root / ".env")
    if isinstance(exc, ForgeError):
        reason = exc.reason
        message = str(exc)
    else:
        reason = ReasonCode.INTERNAL
        message = str(exc)
    typer.echo(f"error reason={reason} {redact(message, secret)}", err=True)
