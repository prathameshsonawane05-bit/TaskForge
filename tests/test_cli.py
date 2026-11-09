"""CLI output must not contain the token."""

import json
import traceback
from pathlib import Path
from types import TracebackType

import httpx
import pytest
from typer.testing import CliRunner

from forge.cli import app
from forge.github import GitHubClient, build_http_client
from forge.models import RepoPayload
from tests.fakes import repository_body, write_project

FAKE_TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"
ENV_TOKEN = "ghp_ENVIRONMENT_TOKEN_SHOULD_NOT_BE_USED"
runner = CliRunner()


def test_cli_refuses_a_repo_that_is_not_allowlisted() -> None:
    result = runner.invoke(app, ["check", "torvalds/linux"])
    text = _command_text(result)
    assert result.exit_code == 1
    assert "refused torvalds/linux reason=not_on_allowlist" in result.stdout
    assert FAKE_TOKEN not in text


def test_cli_missing_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_project(tmp_path, "GITHUB_TOKEN=\n", ["pydantic/pydantic"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", ENV_TOKEN)
    result = runner.invoke(app, ["check", "pydantic/pydantic"])
    text = _command_text(result)
    assert result.exit_code == 2
    assert "error reason=missing_token" in text
    assert "The GitHub call was not made." in text
    assert ENV_TOKEN not in text
    assert FAKE_TOKEN not in text


def test_cli_accepts_allowlisted_repo_and_hides_the_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={FAKE_TOKEN}\n", ["pydantic/pydantic"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", ENV_TOKEN)
    saw_dotenv_token = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal saw_dotenv_token
        saw_dotenv_token = request.headers.get("Authorization") == f"Bearer {FAKE_TOKEN}"
        env_used = request.headers.get("Authorization") == f"Bearer {ENV_TOKEN}"
        if env_used:
            saw_dotenv_token = False
        return httpx.Response(
            200,
            text=repository_body("pydantic/pydantic", "MIT"),
            headers={"ETag": '"live"'},
        )

    def wrapped(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        del transport
        return build_http_client(token, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("forge.github.build_http_client", wrapped)
    result = runner.invoke(app, ["check", "pydantic/pydantic"])
    text = _command_text(result)
    assert result.exit_code == 0
    assert result.stdout.strip() == "accepted pydantic/pydantic spdx=MIT"
    assert saw_dotenv_token
    assert FAKE_TOKEN not in text
    assert ENV_TOKEN not in text
    assert "Authorization" not in text


def test_cli_redacts_a_token_hidden_in_the_license_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={FAKE_TOKEN}\n", ["pydantic/pydantic"])
    monkeypatch.chdir(tmp_path)
    escaped = "".join(f"\\u{ord(char):04x}" for char in FAKE_TOKEN)
    body = '{"full_name":"pydantic/pydantic","license":{"spdx_id":"' + escaped + '"}}'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    def wrapped(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        del transport
        return build_http_client(token, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("forge.github.build_http_client", wrapped)
    result = runner.invoke(app, ["check", "pydantic/pydantic"])
    text = _command_text(result)
    assert result.exit_code == 1
    assert "reason=license_not_allowed" in result.stdout
    assert "spdx=[REDACTED]" in result.stdout
    assert FAKE_TOKEN not in text


def test_cli_funnel_refuses_a_repo_that_is_not_allowlisted() -> None:
    result = runner.invoke(app, ["funnel", "torvalds/linux", "--limit", "30"])
    text = _command_text(result)
    assert result.exit_code == 1
    assert "refused torvalds/linux reason=not_on_allowlist" in result.stdout
    assert FAKE_TOKEN not in text
    assert ENV_TOKEN not in text


def test_cli_funnel_rejects_an_invalid_name() -> None:
    result = runner.invoke(app, ["funnel", "not a repo", "--limit", "30"])
    text = _command_text(result)
    assert result.exit_code == 2
    assert "error reason=invalid_repo" in text


def test_cli_funnel_rejects_a_non_positive_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, "GITHUB_TOKEN=\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["funnel", "acme/widgets", "--limit", "0"])
    text = _command_text(result)
    assert result.exit_code == 2
    assert "error reason=config_error" in text
    assert "positive" in text


def test_cli_funnel_prints_counts_without_the_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={FAKE_TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", ENV_TOKEN)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if request.url.path.endswith("/files"):
            body = json.dumps(
                [
                    {"filename": "pkg/widget.py", "patch": "@@\n+x\n"},
                    {"filename": "tests/test_widget.py", "patch": "@@\n+y\n"},
                ]
            )
            return httpx.Response(200, text=body)
        body = json.dumps(
            [
                {
                    "number": 7,
                    "title": "Handle empty input",
                    "body": "Fixes #12",
                    "merged_at": "2024-01-01T00:00:00Z",
                    "changed_files": 2,
                    "additions": 10,
                    "deletions": 1,
                }
            ]
        )
        return httpx.Response(200, text=body)

    def wrapped(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        del transport
        return build_http_client(token, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("forge.github.build_http_client", wrapped)
    result = runner.invoke(app, ["funnel", "acme/widgets", "--limit", "30"])
    text = _command_text(result)
    assert result.exit_code == 0
    assert "considered 1" in result.stdout
    assert "accepted 1" in result.stdout
    assert "not_merged 0" in result.stdout
    assert "limit 30" in result.stdout
    assert FAKE_TOKEN not in text
    assert ENV_TOKEN not in text


def test_cli_error_string_hides_a_token_raised_by_the_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={FAKE_TOKEN}\n", ["pydantic/pydantic"])
    monkeypatch.chdir(tmp_path)

    def explode(self: GitHubClient, owner: str, name: str) -> RepoPayload:
        del self, owner, name
        raise RuntimeError(f"request failed Authorization: Bearer {FAKE_TOKEN}")

    monkeypatch.setattr(GitHubClient, "get_repository", explode)
    result = runner.invoke(app, ["check", "pydantic/pydantic"])
    text = _command_text(result)
    assert result.exit_code == 2
    assert "error reason=internal" in text
    assert "[REDACTED]" in text
    assert FAKE_TOKEN not in text
    assert "Authorization: [REDACTED]" in text


def _command_text(result: object) -> str:
    parts = [
        _string_attr(result, "stdout"),
        _string_attr(result, "stderr"),
        _string_attr(result, "output"),
    ]
    exception = getattr(result, "exception", None)
    if exception is not None:
        parts.append(str(exception))
        parts.append(repr(exception))
    parts.append(_traceback_text(getattr(result, "exc_info", None)))
    return "\n".join(parts)


def _string_attr(obj: object, name: str) -> str:
    value = getattr(obj, name, "")
    return value if isinstance(value, str) else ""


def _traceback_text(exc_info: object) -> str:
    if not isinstance(exc_info, tuple) or len(exc_info) != 3:
        return ""
    exc_type, exc_value, exc_tb = exc_info
    if not isinstance(exc_type, type) or not issubclass(exc_type, BaseException):
        return ""
    if not isinstance(exc_value, BaseException):
        return ""
    tb = exc_tb if isinstance(exc_tb, TracebackType) else None
    return "".join(traceback.format_exception(exc_type, exc_value, tb))
