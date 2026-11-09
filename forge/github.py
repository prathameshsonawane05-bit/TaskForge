"""GitHub API client with a SQLite body cache and one backoff on 403 or 429.

Requests send If-None-Match when a cached ETag exists. A 304 response returns
the cached body. A 403 or 429 waits using Retry-After, or the rate-limit
reset when the remaining quota is zero, then fails. The wait is capped so a
multi-hour reset cannot stall the process. The token is never written into
an exception, a log line, or the cache.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from forge import __version__
from forge.errors import GitHubError, RateLimitError, redact
from forge.models import ReasonCode, RepoPayload

API_ROOT = "https://api.github.com"
MAX_BACKOFF_SECONDS = 60.0
DEFAULT_BACKOFF_SECONDS = 1.0
_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_RETRY_SECONDS = re.compile(r"^\d+(?:\.\d+)?$")
_RESET_EPOCH = re.compile(r"^\d+$")


@dataclass(frozen=True)
class Backoff:
    """How long to wait before failing a 403 or 429."""

    delay: float
    requested: float
    source: str
    capped: bool


@dataclass(frozen=True)
class CachedResponse:
    etag: str | None
    body: str


class ResponseCache:
    """SQLite cache keyed by the request URL. The token is not part of the key."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = sqlite3.connect(path)
        path.chmod(0o600)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                url TEXT PRIMARY KEY,
                etag TEXT,
                body TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, url: str, secret: str) -> CachedResponse | None:
        row = self._conn.execute(
            "SELECT etag, body FROM responses WHERE url = ?",
            (url,),
        ).fetchone()
        parsed = _row_pair(row)
        if parsed is None:
            return None
        etag, body = parsed
        if _contains_secret(secret, url, etag, body):
            self._conn.execute("DELETE FROM responses WHERE url = ?", (url,))
            self._conn.commit()
            self._conn.execute("VACUUM")
            self._path.chmod(0o600)
            raise GitHubError(
                "Deleted a cached GitHub response that contained the token.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        return CachedResponse(etag=etag, body=body)

    def put(self, url: str, etag: str | None, body: str, secret: str) -> None:
        if _contains_secret(secret, url, etag, body):
            raise GitHubError(
                "Refusing to cache a GitHub response that echoed the token.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        fetched_at = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO responses (url, etag, body, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                etag = excluded.etag,
                body = excluded.body,
                fetched_at = excluded.fetched_at
            """,
            (url, etag, body, fetched_at),
        )
        self._conn.commit()
        self._path.chmod(0o600)


class GitHubClient:
    """Small client for repository metadata. It owns its HTTP client and cache."""

    def __init__(
        self,
        token: str,
        cache_path: Path,
        *,
        http_client: httpx.Client | None = None,
        sleeper: Callable[[float], None] | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        if token == "":
            raise GitHubError(
                "GitHub client requires a token loaded from .env.",
                reason=ReasonCode.MISSING_TOKEN,
            )
        self._token = token
        owns_http = http_client is None
        self._http = http_client if http_client is not None else build_http_client(token)
        try:
            self._cache = ResponseCache(cache_path)
        except Exception:
            if owns_http:
                self._http.close()
            raise
        self._sleep = sleeper if sleeper is not None else time.sleep
        self._now = now if now is not None else time.time

    def close(self) -> None:
        self._cache.close()
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_repository(self, owner: str, name: str) -> RepoPayload:
        url = repository_url(owner, name)
        cached = self._cache.get(url, self._token)
        headers: dict[str, str] = {}
        if cached is not None and cached.etag:
            headers["If-None-Match"] = cached.etag
        try:
            response = self._http.get(url, headers=headers)
        except Exception as exc:
            raise GitHubError(
                f"GitHub request failed: {redact(str(exc), self._token)}",
                reason=ReasonCode.GITHUB_ERROR,
            ) from None
        return self._interpret(url, response, cached)

    def _interpret(
        self,
        url: str,
        response: httpx.Response,
        cached: CachedResponse | None,
    ) -> RepoPayload:
        status = response.status_code
        if status in (403, 429):
            plan = backoff_plan(response.headers, self._now())
            self._sleep(plan.delay)
            raise RateLimitError(_rate_limit_message(status, plan))
        if status == 304:
            if cached is None:
                raise GitHubError(
                    "GitHub returned 304 but there was no cached body for this URL.",
                    reason=ReasonCode.GITHUB_ERROR,
                )
            return _payload_from_body(cached.body)
        if 300 <= status < 400:
            raise GitHubError(
                f"GitHub returned HTTP {status}. Refusing to follow redirects.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        if status == 404:
            raise GitHubError(
                "GitHub could not find that repository.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        if status != 200:
            snippet = redact(response.text[:300], self._token).replace("\n", " ").strip()
            detail = f" {snippet}" if snippet else ""
            raise GitHubError(
                f"GitHub returned HTTP {status}.{detail}",
                reason=ReasonCode.GITHUB_ERROR,
            )
        etag = response.headers.get("ETag")
        self._cache.put(url, etag, response.text, self._token)
        return _payload_from_body(response.text)


def build_http_client(
    token: str,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Build a client that does not follow redirects or read proxy settings."""
    return httpx.Client(
        transport=transport,
        timeout=30.0,
        follow_redirects=False,
        trust_env=False,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"taskforge/{__version__}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def repository_url(owner: str, name: str) -> str:
    if not _valid_segment(owner) or not _valid_segment(name):
        raise GitHubError(
            "Repository owner and name must use letters, numbers, dots, underscores, or hyphens.",
            reason=ReasonCode.INVALID_REPO,
        )
    return f"{API_ROOT}/repos/{owner}/{name}"


def backoff_plan(headers: httpx.Headers, now: float) -> Backoff:
    """Prefer Retry-After. Otherwise use the reset time when the quota is exhausted."""
    retry_after = headers.get("Retry-After")
    if retry_after is not None:
        parsed = _parse_retry_after(retry_after, now)
        if parsed is not None:
            return _cap(parsed, "Retry-After")
    remaining = headers.get("X-RateLimit-Remaining")
    reset = headers.get("X-RateLimit-Reset")
    if remaining is not None and remaining.strip() == "0" and reset is not None:
        reset_text = reset.strip()
        if _RESET_EPOCH.fullmatch(reset_text):
            requested = max(0.0, float(reset_text) - now)
            return _cap(requested, "X-RateLimit-Reset")
    return Backoff(
        delay=DEFAULT_BACKOFF_SECONDS,
        requested=DEFAULT_BACKOFF_SECONDS,
        source="default",
        capped=False,
    )


def _cap(requested: float, source: str) -> Backoff:
    if requested > MAX_BACKOFF_SECONDS:
        return Backoff(
            delay=MAX_BACKOFF_SECONDS,
            requested=requested,
            source=source,
            capped=True,
        )
    return Backoff(delay=requested, requested=requested, source=source, capped=False)


def _parse_retry_after(value: str, now: float) -> float | None:
    stripped = value.strip()
    if _RETRY_SECONDS.fullmatch(stripped):
        return float(stripped)
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, parsed.timestamp() - now)


def _rate_limit_message(status: int, plan: Backoff) -> str:
    waited = _format_seconds(plan.delay)
    if plan.capped:
        asked = _format_seconds(plan.requested)
        return (
            f"GitHub returned HTTP {status}. "
            f"{plan.source} asked for {asked}; "
            f"backed off for {waited} (cap), then failed."
        )
    if plan.source == "default":
        return (
            f"GitHub returned HTTP {status}. "
            f"No usable Retry-After or rate-limit reset. "
            f"Backed off for {waited}, then failed."
        )
    return (
        f"GitHub returned HTTP {status}. Backed off for {waited} using {plan.source}, then failed."
    )


def _format_seconds(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        text = "0"
    unit = "second" if text == "1" else "seconds"
    return f"{text} {unit}"


def _payload_from_body(body: str) -> RepoPayload:
    try:
        return RepoPayload.model_validate_json(body)
    except ValidationError:
        raise GitHubError(
            "GitHub repository payload was missing the fields needed for a license check.",
            reason=ReasonCode.GITHUB_ERROR,
        ) from None


def _valid_segment(segment: str) -> bool:
    if segment in {".", ".."}:
        return False
    return _SEGMENT.fullmatch(segment) is not None


def _contains_secret(secret: str, url: str, etag: str | None, body: str) -> bool:
    if secret == "":
        return False
    if secret in url or secret in body:
        return True
    return etag is not None and secret in etag


def _row_pair(row: object) -> tuple[str | None, str] | None:
    if row is None:
        return None
    if not isinstance(row, tuple) or len(row) != 2:
        raise GitHubError(
            "Cached GitHub response row had an unexpected shape.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    etag_cell = row[0]
    body_cell = row[1]
    if etag_cell is not None and not isinstance(etag_cell, str):
        raise GitHubError(
            "Cached GitHub response had a non-text ETag.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    if not isinstance(body_cell, str):
        raise GitHubError(
            "Cached GitHub response had a non-text body.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return etag_cell, body_cell
