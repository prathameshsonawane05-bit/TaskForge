"""Loader for the small allowlist.yaml subset this project writes."""

import re
from dataclasses import dataclass
from pathlib import Path

from forge.errors import ForgeError
from forge.models import ReasonCode

_ENTRY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Allowlist:
    """Repository names as they appear in the file."""

    repos: tuple[str, ...]

    def contains(self, full_name: str) -> bool:
        folded = full_name.casefold()
        return any(repo.casefold() == folded for repo in self.repos)


def load_allowlist(path: Path) -> Allowlist:
    """Parse `repos:` followed by `- owner/name` lines. Comments and blanks are ignored."""
    if not path.is_file():
        raise ForgeError(
            "Allowlist file was not found.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    repos: list[str] = []
    saw_header = False
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "repos:":
            if saw_header:
                raise ForgeError(
                    "Allowlist has more than one repos: header.",
                    reason=ReasonCode.CONFIG_ERROR,
                )
            saw_header = True
            continue
        if not saw_header or not line.startswith("- "):
            raise ForgeError(
                f"Allowlist line {line_number} is not a repo entry.",
                reason=ReasonCode.CONFIG_ERROR,
            )
        entry = line[2:].strip()
        if _ENTRY.fullmatch(entry) is None or _bad_segment(entry):
            raise ForgeError(
                f"Allowlist line {line_number} is not owner/name.",
                reason=ReasonCode.CONFIG_ERROR,
            )
        repos.append(entry)
    if not saw_header:
        raise ForgeError(
            "Allowlist is missing a repos: header.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if not repos:
        raise ForgeError(
            "Allowlist does not name any repositories.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    folded = [repo.casefold() for repo in repos]
    if len(set(folded)) != len(folded):
        raise ForgeError(
            "Allowlist names the same repository more than once.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    return Allowlist(repos=tuple(repos))


def _bad_segment(full_name: str) -> bool:
    owner, name = full_name.split("/", maxsplit=1)
    return owner in {".", ".."} or name in {".", ".."}
