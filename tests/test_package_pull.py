"""package-pull refusals write no files. These tests do not call Docker."""

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from forge.cli import app
from forge.github import build_http_client
from forge.package import _write_pull_package
from tests.fakes import repository_body, write_project

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"
runner = CliRunner()


def test_package_pull_refuses_a_repo_that_is_not_allowlisted() -> None:
    result = runner.invoke(app, ["package-pull", "torvalds/linux", "1"])
    assert result.exit_code == 1
    assert result.stdout.strip() == "refused torvalds/linux#1 reason=not_on_allowlist"
    assert "ghp_" not in result.stdout
    assert not Path("output/torvalds-linux-1").exists()


def test_filter_rejection_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if request.url.path == "/repos/acme/widgets/pulls/7":
            body = {
                "number": 7,
                "title": "Draft",
                "body": "Fixes #12",
                "merged_at": None,
                "changed_files": 1,
                "additions": 1,
                "deletions": 0,
            }
            return httpx.Response(200, text=json.dumps(body))
        return httpx.Response(404, text="missing")

    def wrapped(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        del transport
        return build_http_client(token, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("forge.github.build_http_client", wrapped)
    result = runner.invoke(app, ["package-pull", "acme/widgets", "7"])
    text = result.stdout + (result.stderr or "")
    assert result.exit_code == 1
    assert result.stdout.strip() == "refused acme/widgets#7 reason=not_merged"
    assert not (tmp_path / "output").exists()
    assert TOKEN not in text


def test_file_with_no_patch_writes_no_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        path = request.url.path
        if path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if path == "/repos/acme/widgets/pulls/7":
            body = {
                "number": 7,
                "title": "Handle empty input",
                "body": "Fixes #12",
                "merged_at": "2024-01-01T00:00:00Z",
                "changed_files": 3,
                "additions": 3,
                "deletions": 1,
            }
            return httpx.Response(200, text=json.dumps(body))
        if path == "/repos/acme/widgets/pulls/7/files":
            files = [
                {
                    "filename": "pkg/widget.py",
                    "status": "modified",
                    "patch": "@@ -1 +1 @@\n-old\n+new\n",
                },
                {
                    "filename": "tests/test_widget.py",
                    "status": "modified",
                    "patch": "@@ -1 +1 @@\n-assert False\n+assert True\n",
                },
                {"filename": "notes.txt", "status": "modified", "patch": None},
            ]
            return httpx.Response(200, text=json.dumps(files))
        if path == "/repos/acme/widgets/issues/12":
            issue = {
                "number": 12,
                "html_url": "https://github.com/acme/widgets/issues/12",
                "title": "Empty input",
                "body": "Steps",
            }
            return httpx.Response(200, text=json.dumps(issue))
        return httpx.Response(404, text="missing")

    def wrapped(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        del transport
        return build_http_client(token, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("forge.github.build_http_client", wrapped)
    result = runner.invoke(app, ["package-pull", "acme/widgets", "7"])
    text = result.stdout + (result.stderr or "")
    assert result.exit_code == 1
    assert result.stdout.strip() == "refused acme/widgets#7 reason=unsupported_file"
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "data" / "packages").exists()
    assert not any(path.endswith("/commits") or "/git/" in path for path in seen)
    assert TOKEN not in text


@pytest.mark.parametrize(
    ("filename", "patch", "binary"),
    [
        ("assets/logo.png", None, True),
        ("uv.lock", "@@\n+lock\n", False),
    ],
)
def test_binary_and_lockfile_write_no_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    patch: str | None,
    binary: bool,
) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if path == "/repos/acme/widgets/pulls/7":
            body = {
                "number": 7,
                "title": "Handle empty input",
                "body": "Fixes #12",
                "merged_at": "2024-01-01T00:00:00Z",
                "changed_files": 3,
                "additions": 3,
                "deletions": 1,
            }
            return httpx.Response(200, text=json.dumps(body))
        if path == "/repos/acme/widgets/pulls/7/files":
            files = [
                {
                    "filename": "pkg/widget.py",
                    "status": "modified",
                    "patch": "@@ -1 +1 @@\n-old\n+new\n",
                },
                {
                    "filename": "tests/test_widget.py",
                    "status": "modified",
                    "patch": "@@ -1 +1 @@\n-assert False\n+assert True\n",
                },
                {"filename": filename, "status": "modified", "patch": patch, "binary": binary},
            ]
            return httpx.Response(200, text=json.dumps(files))
        return httpx.Response(404, text="missing")

    def wrapped(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        del transport
        return build_http_client(token, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("forge.github.build_http_client", wrapped)
    result = runner.invoke(app, ["package-pull", "acme/widgets", "7"])
    text = result.stdout + (result.stderr or "")
    assert result.exit_code == 1
    assert result.stdout.strip() == "refused acme/widgets#7 reason=unsupported_file"
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "data" / "packages").exists()
    assert TOKEN not in text


def test_pull_package_records_upstream_attribution(tmp_path: Path) -> None:
    directory = _write_pull_package(
        root=tmp_path,
        owner="pallets",
        name="click",
        number=3858,
        spdx="BSD-3-Clause",
        issue_url="https://github.com/pallets/click/issues/3822",
        base="a" * 40,
        merge="b" * 40,
        head="c" * 40,
        instruction="# Title\n\nTitle\n",
        source_patch="diff --git a/src/click/types.py b/src/click/types.py\n",
        test_patch="diff --git a/tests/test_types/test_Path.py b/tests/test_types/test_Path.py\n",
        fail_to_pass=("tests/test_types/test_Path.py::test_one",),
        pass_to_pass=("tests/test_keep.py::test_truth",),
    )
    assert directory == tmp_path / "output" / "pallets-click-3858"
    assert not str(directory).endswith("output/sample/pallets-click-3858")
    task = json.loads((directory / "task.json").read_text(encoding="utf-8"))
    assert task["repo"] == "pallets/click"
    assert task["license"] == "BSD-3-Clause"
    assert task["pr_url"] == "https://github.com/pallets/click/pull/3858"
    assert task["issue_url"] == "https://github.com/pallets/click/issues/3822"
    assert task["base_commit"] == "a" * 40
    assert task["difficulty_signals"] == (
        "Difficulty is an estimate. This task was not run against an agent."
    )
    attribution = (directory / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "Repository: pallets/click" in attribution
    assert "License: BSD-3-Clause" in attribution
    assert "https://github.com/pallets/click/pull/3858" in attribution
    assert "https://github.com/pallets/click/issues/3822" in attribution
    assert f"Base commit: {'a' * 40}" in attribution
    assert f"Merge commit: {'b' * 40}" in attribution
    assert f"Head commit: {'c' * 40}" in attribution
    assert "no upstream" not in attribution
