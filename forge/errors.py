"""Exceptions that never include the GitHub token."""

import re

from forge.models import ReasonCode

_AUTHORIZATION = re.compile(r"(?i)\bAuthorization\s*[:=]\s*(?:Bearer\s+)?\S+")
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")


def redact(text: str, secret: str) -> str:
    """Remove a token and Authorization values from text that might be shown."""
    redacted = text
    if secret:
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _AUTHORIZATION.sub("Authorization: [REDACTED]", redacted)
    redacted = _BEARER.sub("Bearer [REDACTED]", redacted)
    return redacted


class ForgeError(Exception):
    """Expected failure with a stable reason code."""

    def __init__(self, message: str, *, reason: ReasonCode) -> None:
        super().__init__(message)
        self.reason = reason


class MissingTokenError(ForgeError):
    """GITHUB_TOKEN is absent from .env or still the example placeholder."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason=ReasonCode.MISSING_TOKEN)


class RateLimitError(ForgeError):
    """GitHub returned 403 or 429. The client already waited, then failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason=ReasonCode.RATE_LIMITED)


class GitHubError(ForgeError):
    """The GitHub API response could not be used."""

    def __init__(self, message: str, *, reason: ReasonCode = ReasonCode.GITHUB_ERROR) -> None:
        super().__init__(message, reason=reason)
