"""Paths and the .env token loader.

The token is read only from .env. The process environment is ignored so a
shell export cannot override the file or sneak into a log line from this loader.
"""

import re
from pathlib import Path

from forge.errors import ForgeError, MissingTokenError
from forge.models import ReasonCode

_TOKEN_LINE = re.compile(r"^(?:export\s+)?GITHUB_TOKEN=(.*)$")
_PLACEHOLDER = "your_token_here"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk parents until pyproject.toml is found."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ForgeError(
        "Could not find pyproject.toml by walking up from the current directory.",
        reason=ReasonCode.CONFIG_ERROR,
    )


def allowlist_path(root: Path) -> Path:
    return root / "forge" / "allowlist.yaml"


def default_cache_path(root: Path) -> Path:
    return root / "data" / "github_cache.sqlite"


def load_github_token(env_path: Path) -> str:
    """Return the token from .env, or raise without echoing any secret."""
    if not env_path.is_file():
        raise MissingTokenError(
            "GITHUB_TOKEN is missing. Add it to .env (see .env.example). "
            "The GitHub call was not made."
        )
    found: str | None = None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _TOKEN_LINE.match(line)
        if match is None:
            continue
        found = _unquote(match.group(1).strip())
    if found is None or found == "" or found == _PLACEHOLDER:
        raise MissingTokenError(
            "GITHUB_TOKEN is missing or empty in .env. The GitHub call was not made."
        )
    return found


def secret_for_redaction(env_path: Path) -> str:
    """Token used only to scrub error text. Missing tokens become an empty string."""
    try:
        return load_github_token(env_path)
    except Exception:
        return ""


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
