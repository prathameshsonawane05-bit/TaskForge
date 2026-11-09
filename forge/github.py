"""GitHub API client with a SQLite body cache and rate-limit retries.

One client serves every GET. A 200 body is cached only after it parses as a
JSON object or array. Requests send If-None-Match when a cached ETag exists,
and a 304 returns that cached document. A real rate limit (Retry-After, or
X-RateLimit-Reset when X-RateLimit-Remaining is 0, or HTTP 429) is retried up
to 3 times. Each wait is capped at 60 seconds. A 403 with neither rate-limit
signal is github_error and is not slept on. Redirects are not followed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import ValidationError

from forge import __version__
from forge.errors import GitHubError, RateLimitError, redact
from forge.models import ReasonCode, RepoPayload

API_ROOT = "https://api.github.com"
MAX_BACKOFF_SECONDS = 60.0
MAX_RATE_LIMIT_RETRIES = 3
HEADERLESS_429_SECONDS = 1.0
_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_RETRY_SECONDS = re.compile(r"^\d+(?:\.\d+)?$")
_RESET_EPOCH = re.compile(r"^\d+$")
_NEXT_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


@dataclass(frozen=True)
class Wait:
    """A counted backoff. `delay` is what the client sleeps."""

    delay: float
    requested: float
    source: str
    capped: bool


@dataclass(frozen=True)
class CachedResponse:
    etag: str | None
    body: str
    link: str | None


@dataclass(frozen=True)
class GitHubDocument:
    """Parsed JSON document plus the Link header, if GitHub sent one."""

    data: dict[str, object] | list[object]
    link: str | None
    url: str


class ResponseCache:
    """SQLite cache keyed by the request URL. The token is not part of the key."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()
        self._lock_down()

    def close(self) -> None:
        self._conn.close()

    def get(self, url: str, secret: str) -> CachedResponse | None:
        row = self._conn.execute(
            "SELECT etag, body, link FROM responses WHERE url = ?",
            (url,),
        ).fetchone()
        parsed = _row_triple(row)
        if parsed is None:
            return None
        etag, body, link = parsed
        if _contains_secret(secret, url, etag, body, link):
            self._delete_row(url)
            self._conn.execute("VACUUM")
            self._lock_down()
            raise GitHubError(
                "Deleted a cached GitHub response that contained the token.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        return CachedResponse(etag=etag, body=body, link=link)

    def put(
        self,
        url: str,
        etag: str | None,
        body: str,
        link: str | None,
        secret: str,
    ) -> None:
        if _contains_secret(secret, url, etag, body, link):
            raise GitHubError(
                "Refusing to cache a GitHub response that echoed the token.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        fetched_at = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO responses (url, etag, body, link, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                etag = excluded.etag,
                body = excluded.body,
                link = excluded.link,
                fetched_at = excluded.fetched_at
            """,
            (url, etag, body, link, fetched_at),
        )
        self._conn.commit()
        self._lock_down()

    def delete(self, url: str) -> None:
        self._delete_row(url)
        self._lock_down()

    def _delete_row(self, url: str) -> None:
        self._conn.execute("DELETE FROM responses WHERE url = ?", (url,))
        self._conn.commit()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                url TEXT PRIMARY KEY,
                etag TEXT,
                body TEXT NOT NULL,
                link TEXT,
                fetched_at TEXT NOT NULL
            )
            """
        )
        columns = _table_columns(self._conn)
        if "link" not in columns:
            self._conn.execute("ALTER TABLE responses ADD COLUMN link TEXT")
        self._conn.commit()

    def _lock_down(self) -> None:
        """Keep the database and its WAL sidecars unreadable by other users."""
        if self._path.is_file():
            self._path.chmod(0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self._path}{suffix}")
            if sidecar.is_file():
                sidecar.chmod(0o600)


class GitHubClient:
    """Small client for GitHub JSON GETs. It owns its HTTP client and cache."""

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

    def get(self, url: str) -> GitHubDocument:
        """GET one GitHub URL. `url` may be absolute or an API path."""
        target = normalize_github_url(url)
        cached = self._cache.get(target, self._token)
        retries = 0
        ignore_etag = False
        while True:
            headers: dict[str, str] = {}
            if cached is not None and cached.etag and not ignore_etag:
                headers["If-None-Match"] = cached.etag
            response = self._send(target, headers)
            status = response.status_code
            wait = countable_wait(response.headers, self._now())
            if status == 429 or (status == 403 and wait is not None):
                measured = wait
                if measured is None:
                    measured = Wait(
                        delay=HEADERLESS_429_SECONDS,
                        requested=HEADERLESS_429_SECONDS,
                        source="429-without-header",
                        capped=False,
                    )
                if retries >= MAX_RATE_LIMIT_RETRIES:
                    raise RateLimitError(_exhausted_message(status, measured, retries))
                self._sleep(measured.delay)
                retries += 1
                continue
            if status == 403:
                raise GitHubError(
                    "GitHub returned HTTP 403 without Retry-After or an exhausted "
                    "rate-limit reset.",
                    reason=ReasonCode.GITHUB_ERROR,
                )
            if status == 304:
                if cached is None:
                    raise GitHubError(
                        "GitHub returned 304 but there was no cached body for this URL.",
                        reason=ReasonCode.GITHUB_ERROR,
                    )
                try:
                    data = parse_json_document(cached.body)
                except GitHubError:
                    self._cache.delete(target)
                    cached = None
                    ignore_etag = True
                    continue
                link = response.headers.get("Link")
                if link is None:
                    link = cached.link
                return GitHubDocument(data=data, link=link, url=target)
            if 300 <= status < 400:
                raise GitHubError(
                    f"GitHub returned HTTP {status}. Refusing to follow redirects.",
                    reason=ReasonCode.GITHUB_ERROR,
                )
            if status == 404:
                raise GitHubError(
                    "GitHub could not find that resource.",
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
            link = response.headers.get("Link")
            if _contains_secret(self._token, target, etag, response.text, link):
                raise GitHubError(
                    "Refusing to cache a GitHub response that echoed the token.",
                    reason=ReasonCode.GITHUB_ERROR,
                )
            data = parse_json_document(response.text)
            self._cache.put(target, etag, response.text, link, self._token)
            return GitHubDocument(data=data, link=link, url=target)

    def get_repository(self, owner: str, name: str) -> RepoPayload:
        document = self.get(repository_url(owner, name))
        if not isinstance(document.data, dict):
            raise GitHubError(
                "GitHub repository payload was not a JSON object.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        try:
            return RepoPayload.model_validate(document.data)
        except ValidationError:
            raise GitHubError(
                "GitHub repository payload was missing the fields needed for a license check.",
                reason=ReasonCode.GITHUB_ERROR,
            ) from None

    def _send(self, url: str, headers: dict[str, str]) -> httpx.Response:
        try:
            return self._http.get(url, headers=headers)
        except Exception as exc:
            raise GitHubError(
                f"GitHub request failed: {redact(str(exc), self._token)}",
                reason=ReasonCode.GITHUB_ERROR,
            ) from None


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


def issue_url(owner: str, name: str, number: int) -> str:
    if number < 1 or not _valid_segment(owner) or not _valid_segment(name):
        raise GitHubError(
            "Issue reference must be owner/name and a positive issue number.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return f"{API_ROOT}/repos/{owner}/{name}/issues/{number}"


def repository_url(owner: str, name: str) -> str:
    if not _valid_segment(owner) or not _valid_segment(name):
        raise GitHubError(
            "Repository owner and name must use letters, numbers, dots, underscores, or hyphens.",
            reason=ReasonCode.INVALID_REPO,
        )
    return f"{API_ROOT}/repos/{owner}/{name}"


def normalize_github_url(url: str) -> str:
    """Accept an API path or an https://api.github.com URL. Reject anything else."""
    if url.startswith("/"):
        url = API_ROOT + url
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "api.github.com":
        raise GitHubError(
            "Refusing a URL that is not on https://api.github.com/.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    if parts.username or parts.password or parts.fragment:
        raise GitHubError(
            "Refusing a GitHub URL with user info or a fragment.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    query_lower = parts.query.lower()
    if "access_token=" in query_lower or "github_token=" in query_lower:
        raise GitHubError(
            "Refusing a GitHub URL that carries a token in the query string.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def next_link(header: str | None) -> str | None:
    """Return the URL marked rel="next", or None when this page is the last."""
    if header is None or header == "":
        return None
    match = _NEXT_LINK.search(header)
    if match is None:
        return None
    return match.group(1)


def countable_wait(headers: httpx.Headers, now: float) -> Wait | None:
    """Retry-After, otherwise the reset time when the remaining quota is zero."""
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
    return None


def parse_json_document(body: str) -> dict[str, object] | list[object]:
    """Parse a JSON object or array. Invalid JSON and other values are errors."""
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError:
        raise GitHubError(
            "GitHub returned invalid JSON.",
            reason=ReasonCode.GITHUB_ERROR,
        ) from None
    if isinstance(parsed, dict):
        result: dict[str, object] = {}
        for key, value in parsed.items():
            if not isinstance(key, str):
                raise GitHubError(
                    "GitHub returned a JSON object with a non-string key.",
                    reason=ReasonCode.GITHUB_ERROR,
                )
            result[key] = value
        return result
    if isinstance(parsed, list):
        items: list[object] = []
        for item in parsed:
            items.append(item)
        return items
    raise GitHubError(
        "GitHub returned JSON that is not an object or array.",
        reason=ReasonCode.GITHUB_ERROR,
    )


def _cap(requested: float, source: str) -> Wait:
    if requested > MAX_BACKOFF_SECONDS:
        return Wait(
            delay=MAX_BACKOFF_SECONDS,
            requested=requested,
            source=source,
            capped=True,
        )
    return Wait(delay=requested, requested=requested, source=source, capped=False)


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


def _exhausted_message(status: int, wait: Wait, retries: int) -> str:
    waited = _format_seconds(wait.delay)
    if wait.capped:
        asked = _format_seconds(wait.requested)
        return (
            f"GitHub returned HTTP {status} after {retries} retries. "
            f"{wait.source} asked for {asked}; "
            f"each wait was capped at {waited}. Then failed."
        )
    return (
        f"GitHub returned HTTP {status} after {retries} retries. "
        f"Last wait was {waited} using {wait.source}. Then failed."
    )


def _format_seconds(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        text = "0"
    unit = "second" if text == "1" else "seconds"
    return f"{text} {unit}"


def _valid_segment(segment: str) -> bool:
    if segment in {".", ".."}:
        return False
    return _SEGMENT.fullmatch(segment) is not None


def _contains_secret(
    secret: str,
    url: str,
    etag: str | None,
    body: str,
    link: str | None,
) -> bool:
    if secret == "":
        return False
    if secret in url or secret in body:
        return True
    if etag is not None and secret in etag:
        return True
    return link is not None and secret in link


def _table_columns(connection: sqlite3.Connection) -> set[str]:
    names: set[str] = set()
    for row in connection.execute("PRAGMA table_info(responses)"):
        parsed = _cell(row, 1)
        if isinstance(parsed, str):
            names.add(parsed)
    return names


def _row_triple(row: object) -> tuple[str | None, str, str | None] | None:
    if row is None:
        return None
    if not isinstance(row, tuple) or len(row) != 3:
        raise GitHubError(
            "Cached GitHub response row had an unexpected shape.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    etag = _text_or_none(row[0], "ETag")
    body = _text(row[1], "body")
    link = _text_or_none(row[2], "link")
    return etag, body, link


def _cell(row: object, index: int) -> object:
    if not isinstance(row, tuple) or index >= len(row):
        raise GitHubError(
            "SQLite returned an unexpected table-info row.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return row[index]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise GitHubError(
            f"Cached GitHub response had a non-text {label}.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return value


def _text_or_none(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)
