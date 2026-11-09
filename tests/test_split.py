"""Split an accepted pull request and extract its first closing reference."""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from forge.cli import app
from forge.errors import ForgeError
from forge.filters import first_closing_reference
from forge.github import build_http_client
from forge.models import PullFilePayload
from forge.split import partition_files, render_file_diff, run_split
from tests.fakes import make_client, repository_body, write_project

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"
runner = CliRunner()

SOURCE_HUNK = "@@ -1 +1,2 @@\n hello\n+world\n"
TEST_HUNK = "@@ -1 +1,2 @@\n assert False\n+assert True\n"
RENAME_HUNK = "@@ -1 +1,2 @@\n old\n+new\n"
OTHER_HUNK = "@@ -1 +1 @@\n-readme\n+docs\n"


def _pull_body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": 7,
        "title": "Handle empty input",
        "body": "Fixes #12",
        "merged_at": "2024-01-01T00:00:00Z",
        "changed_files": 4,
        "additions": 4,
        "deletions": 1,
    }
    payload.update(overrides)
    return payload


def _files() -> list[dict[str, object]]:
    return [
        {"filename": "pkg/widget.py", "status": "modified", "patch": SOURCE_HUNK},
        {
            "filename": "pkg/renamed.py",
            "status": "renamed",
            "previous_filename": "pkg/old.py",
            "patch": RENAME_HUNK,
        },
        {"filename": "tests/test_widget.py", "status": "modified", "patch": TEST_HUNK},
        {"filename": "README.md", "status": "modified", "patch": OTHER_HUNK},
    ]


def _issue(number: int, owner: str, name: str) -> dict[str, object]:
    return {
        "number": number,
        "html_url": f"https://github.com/{owner}/{name}/issues/{number}",
        "title": "Empty input",
        "body": "Steps to reproduce",
    }


def test_three_reference_forms_fetch_that_issue(tmp_path: Path) -> None:
    cases = [
        ("Fixes #12", "/repos/acme/widgets/issues/12", "acme", "widgets", 12),
        ("Fixes acme/other#4", "/repos/acme/other/issues/4", "acme", "other", 4),
        (
            "Resolves https://github.com/octo/tools/issues/9.",
            "/repos/octo/tools/issues/9",
            "octo",
            "tools",
            9,
        ),
    ]
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    for body, issue_path, owner, name, number in cases:
        urls: list[str] = []
        handler = _reference_handler(urls, body, issue_path, owner, name, number)
        cache = tmp_path / f"cache-{number}.sqlite"
        with make_client(TOKEN, cache, handler) as client:
            outcome = run_split("acme/widgets", 7, root=tmp_path, client=client)
        assert outcome.report is not None
        assert outcome.report.issue_number == number
        assert outcome.report.issue_url == f"https://github.com/{owner}/{name}/issues/{number}"
        assert outcome.report.issue_title == "Empty input"
        assert outcome.report.issue_body == "Steps to reproduce"
        assert issue_path in urls
        assert TOKEN not in outcome.report.issue_url


def test_first_reference_wins() -> None:
    body = "Fixes #2. Also closes https://github.com/acme/widgets/issues/9."
    ref = first_closing_reference(body, repo_owner="acme", repo_name="widgets")
    assert ref is not None
    assert (ref.owner, ref.name, ref.number) == ("acme", "widgets", 2)


def test_non_adjacent_keyword_does_not_link() -> None:
    body = "Please fix the parser.\n\nTracked as #44."
    assert first_closing_reference(body, repo_owner="acme", repo_name="widgets") is None


def test_rejected_pull_does_not_fetch_files(tmp_path: Path) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(request.url.path)
        if request.url.path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if request.url.path == "/repos/acme/widgets/pulls/7":
            return httpx.Response(200, text=json.dumps(_pull_body(merged_at=None)))
        return httpx.Response(404, text="missing")

    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        outcome = run_split("acme/widgets", 7, root=tmp_path, client=client)
    assert outcome.report is None
    assert outcome.filter_reason is not None
    assert outcome.filter_reason.value == "not_merged"
    assert not any(path.endswith("/files") for path in urls)
    assert "/repos/acme/widgets/issues/12" not in urls


def test_other_file_is_left_out_and_patches_apply(tmp_path: Path) -> None:
    files = [
        PullFilePayload(filename="pkg/widget.py", status="modified", patch=SOURCE_HUNK),
        PullFilePayload(
            filename="pkg/renamed.py",
            status="renamed",
            previous_filename="pkg/old.py",
            patch=RENAME_HUNK,
        ),
        PullFilePayload(filename="tests/test_widget.py", status="modified", patch=TEST_HUNK),
        PullFilePayload(filename="README.md", status="modified", patch=OTHER_HUNK),
    ]
    source, test, other = partition_files(files)
    assert [item.filename for item in other] == ["README.md"]
    source_patch = render_file_diff(source[0]) + render_file_diff(source[1])
    test_patch = render_file_diff(test[0])
    assert "README.md" not in source_patch
    assert "README.md" not in test_patch
    assert "rename from pkg/old.py" in source_patch
    assert "rename to pkg/renamed.py" in source_patch
    assert "diff --git a/pkg/widget.py b/pkg/widget.py" in source_patch
    assert "--- a/pkg/old.py" in source_patch
    assert "+++ b/pkg/renamed.py" in source_patch

    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pkg" / "widget.py").write_text("hello\n", encoding="utf-8")
    (repo / "pkg" / "old.py").write_text("old\n", encoding="utf-8")
    (repo / "tests" / "test_widget.py").write_text("assert False\n", encoding="utf-8")
    (repo / "README.md").write_text("readme\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    solution = tmp_path / "solution.patch"
    tests = tmp_path / "test.patch"
    solution.write_text(source_patch, encoding="utf-8")
    tests.write_text(test_patch, encoding="utf-8")
    checked = subprocess.run(
        ["git", "apply", "--check", str(solution), str(tests)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr


def test_missing_patch_is_an_error_not_an_empty_diff() -> None:
    with pytest.raises(ForgeError) as caught:
        render_file_diff(PullFilePayload(filename="pkg/widget.py", patch=None))
    message = str(caught.value)
    assert "no patch" in message
    assert message != ""
    assert caught.value.reason == "github_error"


def _reference_handler(
    urls: list[str],
    body: str,
    issue_path: str,
    owner: str,
    name: str,
    number: int,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(request.url.path)
        path = request.url.path
        if path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if path == "/repos/acme/widgets/pulls/7":
            return httpx.Response(200, text=json.dumps(_pull_body(body=body, changed_files=2)))
        if path == "/repos/acme/widgets/pulls/7/files":
            files = [
                {"filename": "pkg/widget.py", "status": "modified", "patch": SOURCE_HUNK},
                {"filename": "tests/test_widget.py", "status": "modified", "patch": TEST_HUNK},
            ]
            return httpx.Response(200, text=json.dumps(files))
        if path == issue_path:
            return httpx.Response(200, text=json.dumps(_issue(number, owner, name)))
        return httpx.Response(404, text="missing")

    return handler


def test_cli_split_prints_a_refusal_without_the_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if request.url.path == "/repos/acme/widgets/pulls/7":
            return httpx.Response(200, text=json.dumps(_pull_body(merged_at=None)))
        return httpx.Response(404, text="missing")

    def wrapped(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        del transport
        return build_http_client(token, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("forge.github.build_http_client", wrapped)
    result = runner.invoke(app, ["split", "acme/widgets", "7"])
    text = f"{result.stdout}{result.stderr}"
    assert result.exit_code == 1
    assert "refused acme/widgets#7 reason=not_merged" in result.stdout
    assert TOKEN not in text


def test_cli_split_prints_files_and_issue_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if path == "/repos/acme/widgets/pulls/7":
            return httpx.Response(200, text=json.dumps(_pull_body()))
        if path.endswith("/files"):
            return httpx.Response(200, text=json.dumps(_files()))
        if path == "/repos/acme/widgets/issues/12":
            return httpx.Response(200, text=json.dumps(_issue(12, "acme", "widgets")))
        return httpx.Response(404, text="missing")

    def wrapped(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        del transport
        return build_http_client(token, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("forge.github.build_http_client", wrapped)
    result = runner.invoke(app, ["split", "acme/widgets", "7"])
    text = f"{result.stdout}{result.stderr}"
    assert result.exit_code == 0, result.stderr
    assert "source pkg/widget.py" in result.stdout
    assert "source pkg/renamed.py" in result.stdout
    assert "test tests/test_widget.py" in result.stdout
    assert "other README.md" in result.stdout
    assert "issue https://github.com/acme/widgets/issues/12" in result.stdout
    assert TOKEN not in text
