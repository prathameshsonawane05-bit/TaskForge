"""GitHub client tests. The HTTP client is mocked; sockets are blocked."""

import sqlite3
from email.utils import formatdate
from pathlib import Path

import httpx
import pytest

from forge.errors import GitHubError, RateLimitError
from forge.github import build_http_client
from tests.fakes import make_client, repository_body

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"


def test_conditional_get_uses_cached_body_on_304(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    cached_body = repository_body("acme/widgets", "MIT")
    fresh_body = repository_body("acme/widgets", "GPL-3.0")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            assert "if-none-match" not in request.headers
            return httpx.Response(200, text=cached_body, headers={"ETag": 'W/"v1"'})
        assert request.headers["If-None-Match"] == 'W/"v1"'
        return httpx.Response(304, text=fresh_body, headers={"ETag": 'W/"v1"'})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        first = client.get_repository("acme", "widgets")
        second = client.get_repository("acme", "widgets")
    assert first.license is not None and first.license.spdx_id == "MIT"
    assert second.license is not None and second.license.spdx_id == "MIT"
    assert len(calls) == 2


def test_missing_etag_does_not_send_if_none_match(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        client.get_repository("acme", "widgets")
        client.get_repository("acme", "widgets")
    assert "if-none-match" not in calls[0].headers
    assert "if-none-match" not in calls[1].headers


def test_429_retries_then_returns_the_later_success(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(
                429,
                text="slow down",
                headers={"Retry-After": "2", "X-RateLimit-Reset": "1000050"},
            )
        return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))

    with make_client(
        TOKEN,
        tmp_path / "cache.sqlite",
        handler,
        sleeper=slept.append,
        now=lambda: 1_000_000.0,
    ) as client:
        payload = client.get_repository("acme", "widgets")
    assert payload.license is not None and payload.license.spdx_id == "MIT"
    assert slept == [2.0, 2.0]
    assert len(calls) == 3


def test_429_fails_after_three_retries(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            429,
            text="slow down",
            headers={"Retry-After": "12", "X-RateLimit-Reset": "1000050"},
        )

    with make_client(
        TOKEN,
        tmp_path / "cache.sqlite",
        handler,
        sleeper=slept.append,
        now=lambda: 1_000_000.0,
    ) as client:
        with pytest.raises(RateLimitError) as caught:
            client.get_repository("acme", "widgets")
    assert slept == [12.0, 12.0, 12.0]
    assert len(calls) == 4
    message = str(caught.value)
    assert caught.value.reason == "rate_limited"
    assert "HTTP 429" in message
    assert "3 retries" in message
    assert "Retry-After" in message
    assert "12 seconds" in message
    assert TOKEN not in message


def test_403_uses_reset_when_quota_is_exhausted(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            403,
            text="api rate limit exceeded",
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1000007"},
        )

    with make_client(
        TOKEN,
        tmp_path / "cache.sqlite",
        handler,
        sleeper=slept.append,
        now=lambda: 1_000_000.0,
    ) as client:
        with pytest.raises(RateLimitError) as caught:
            client.get_repository("acme", "widgets")
    assert slept == [7.0, 7.0, 7.0]
    assert len(calls) == 4
    assert caught.value.reason == "rate_limited"
    assert "X-RateLimit-Reset" in str(caught.value)
    assert TOKEN not in str(caught.value)


def test_bare_403_is_not_a_rate_limit(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(403, text="forbidden")

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler, sleeper=slept.append) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("acme", "widgets")
    assert slept == []
    assert len(calls) == 1
    assert caught.value.reason == "github_error"
    assert not isinstance(caught.value, RateLimitError)
    message = str(caught.value)
    assert "HTTP 403" in message
    assert "rate_limited" not in message
    assert TOKEN not in message


def test_403_with_remaining_quota_does_not_sleep(tmp_path: Path) -> None:
    slept: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text="forbidden",
            headers={"X-RateLimit-Remaining": "40", "X-RateLimit-Reset": "1000007"},
        )

    with make_client(
        TOKEN,
        tmp_path / "cache.sqlite",
        handler,
        sleeper=slept.append,
        now=lambda: 1_000_000.0,
    ) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("acme", "widgets")
    assert slept == []
    assert caught.value.reason == "github_error"


def test_retry_after_http_date(tmp_path: Path) -> None:
    slept: list[float] = []
    now = 1_767_225_600.0
    header = formatdate(now + 15, usegmt=True)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": header})

    with make_client(
        TOKEN,
        tmp_path / "cache.sqlite",
        handler,
        sleeper=slept.append,
        now=lambda: now,
    ) as client:
        with pytest.raises(RateLimitError):
            client.get_repository("acme", "widgets")
    assert slept == [pytest.approx(15.0), pytest.approx(15.0), pytest.approx(15.0)]


def test_retry_after_is_capped(tmp_path: Path) -> None:
    slept: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "5000"})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler, sleeper=slept.append) as client:
        with pytest.raises(RateLimitError) as caught:
            client.get_repository("acme", "widgets")
    assert slept == [60.0, 60.0, 60.0]
    message = str(caught.value)
    assert "5000 seconds" in message
    assert "cap" in message
    assert "3 retries" in message
    assert TOKEN not in message


def test_response_that_echoes_the_token_is_not_cached_or_returned(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite"

    def handler(_request: httpx.Request) -> httpx.Response:
        body = repository_body("acme/widgets", "MIT").replace("MIT", TOKEN)
        return httpx.Response(200, text=body, headers={"ETag": '"ok"'})

    with make_client(TOKEN, cache_path, handler) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("acme", "widgets")
    message = str(caught.value)
    assert TOKEN not in message
    assert "echoed the token" in message
    blob = _cache_bytes(cache_path)
    assert TOKEN.encode() not in blob


def test_request_exception_redacts_the_token(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"boom Authorization: Bearer {TOKEN}", request=request)

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("acme", "widgets")
    message = str(caught.value)
    assert TOKEN not in message
    assert "Authorization: [REDACTED]" in message
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_http_500_does_not_include_request_headers(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server blew up")

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("acme", "widgets")
    message = str(caught.value)
    assert "HTTP 500" in message
    assert "server blew up" in message
    assert TOKEN not in message
    assert "Authorization" not in message


def test_invalid_json_with_etag_is_not_served_on_the_next_call(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, text="not-json", headers={"ETag": '"bad"'})
        assert "if-none-match" not in request.headers
        return httpx.Response(
            200,
            text=repository_body("acme/widgets", "MIT"),
            headers={"ETag": '"good"'},
        )

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("acme", "widgets")
        payload = client.get_repository("acme", "widgets")
    assert "invalid JSON" in str(caught.value)
    assert TOKEN not in str(caught.value)
    assert payload.license is not None and payload.license.spdx_id == "MIT"
    assert len(calls) == 2
    assert "if-none-match" not in calls[1].headers


def test_get_uses_the_same_cache_for_json_arrays(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    link = '<https://api.github.com/repos/acme/widgets/pulls?page=2>; rel="next"'

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, text="[1, 2]", headers={"ETag": '"a"', "Link": link})
        assert request.headers["If-None-Match"] == '"a"'
        return httpx.Response(304, headers={"ETag": '"a"'})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        first = client.get("https://api.github.com/repos/acme/widgets/pulls?state=closed")
        second = client.get("/repos/acme/widgets/pulls?state=closed")
    assert first.data == [1, 2]
    assert second.data == [1, 2]
    assert first.link == link
    assert second.link == link
    assert len(calls) == 2


def test_sqlite_sidecars_are_private(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=repository_body("acme/widgets", "MIT"),
            headers={"ETag": '"e"'},
        )

    with make_client(TOKEN, cache_path, handler) as client:
        client.get_repository("acme", "widgets")
        assert cache_path.stat().st_mode & 0o777 == 0o600
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{cache_path}{suffix}")
            assert sidecar.is_file()
            assert sidecar.stat().st_mode & 0o777 == 0o600


def test_poisoned_cache_row_is_removed(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=repository_body("acme/widgets", "MIT"),
            headers={"ETag": '"clean"'},
        )

    with make_client(TOKEN, cache_path, handler) as client:
        client.get_repository("acme", "widgets")
    connection = sqlite3.connect(cache_path)
    connection.execute("UPDATE responses SET body = ?", (TOKEN,))
    connection.commit()
    connection.close()

    with make_client(TOKEN, cache_path, handler) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("acme", "widgets")
    assert "contained the token" in str(caught.value)
    assert TOKEN not in str(caught.value)
    assert TOKEN.encode() not in _cache_bytes(cache_path)


def test_redirects_are_not_followed(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://example.invalid/secret"})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("acme", "widgets")
    message = str(caught.value)
    assert "Refusing to follow redirects" in message
    assert "example.invalid" not in message
    assert TOKEN not in message


def test_client_sends_bearer_token_without_logging_it(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(0)
    saw = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal saw
        saw = request.headers.get("Authorization") == f"Bearer {TOKEN}"
        return httpx.Response(200, text=repository_body("acme/widgets", "Apache-2.0"))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        payload = client.get_repository("acme", "widgets")
    assert saw
    assert payload.license is not None and payload.license.spdx_id == "Apache-2.0"
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert TOKEN not in logged
    assert "authorization" not in logged.lower()


def test_build_http_client_does_not_follow_redirects_or_trust_env() -> None:
    client = build_http_client(
        TOKEN, transport=httpx.MockTransport(lambda _request: httpx.Response(200))
    )
    try:
        assert client.follow_redirects is False
        assert client.trust_env is False
    finally:
        client.close()


def test_304_without_a_cached_body_fails(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        with pytest.raises(GitHubError) as caught:
            client.get("https://api.github.com/repos/acme/widgets")
    assert "no cached body" in str(caught.value)
    assert TOKEN not in str(caught.value)


def test_dotdot_segment_is_rejected(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("request should not be sent")

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        with pytest.raises(GitHubError) as caught:
            client.get_repository("..", "widgets")
    assert caught.value.reason == "invalid_repo"


def _cache_bytes(path: Path) -> bytes:
    blob = path.read_bytes() if path.is_file() else b""
    for suffix in ("-wal", "-shm"):
        extra = Path(f"{path}{suffix}")
        if extra.is_file():
            blob += extra.read_bytes()
    return blob
