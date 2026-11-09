"""Funnel pagination and the rule that rejection counts add up."""

import json
from pathlib import Path

import httpx

from forge.funnel import format_report, run_funnel
from forge.models import FilterReason
from tests.fakes import make_client, repository_body, write_project

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"


def _pull(number: int, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": number,
        "title": "Handle empty input",
        "body": "Fixes #12",
        "merged_at": "2024-01-01T00:00:00Z",
        "changed_files": 2,
        "additions": 10,
        "deletions": 4,
    }
    payload.update(overrides)
    return payload


def _sample_pulls() -> list[dict[str, object]]:
    return [
        _pull(1, merged_at=None),
        _pull(2, title='Revert "Handle empty input"'),
        _pull(3, changed_files=6),
        _pull(4, additions=200, deletions=101),
        _pull(5, additions=None, deletions=0),
        _pull(6, changed_files=3),
        _pull(7, changed_files=3),
        _pull(8, changed_files=1, additions=8, deletions=0),
        _pull(9, changed_files=1),
        _pull(10, body="No closing keyword here."),
        _pull(11),
    ]


def _file(filename: str, patch: str | None) -> dict[str, object]:
    return {"filename": filename, "patch": patch}


def _files_for(number: int) -> list[dict[str, object]]:
    source = _file("pkg/widget.py", "@@\n+x\n")
    test = _file("tests/test_widget.py", "@@\n+y\n")
    if number == 6:
        return [_file("assets/logo.png", None), source, test]
    if number == 7:
        return [source, test, _file("poetry.lock", "@@\n+lock\n")]
    if number == 8:
        return [_file("README.md", "@@\n+doc\n")]
    if number == 9:
        return [source]
    return [source, test]


def test_second_page_is_requested_when_the_limit_allows_it(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    urls: list[str] = []
    link = (
        "<https://api.github.com/repos/acme/widgets/pulls?state=closed&per_page=100&page=2>; "
        'rel="next"'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        path = request.url.path
        if path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if path.endswith("/files"):
            return httpx.Response(200, text=json.dumps(_files_for(11)))
        if "page=2" in str(request.url):
            return httpx.Response(200, text=json.dumps([_pull(2)]))
        return httpx.Response(200, text=json.dumps([_pull(1)]), headers={"Link": link})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        outcome = run_funnel("acme/widgets", root=tmp_path, limit=2, client=client)
    assert outcome.report is not None
    assert outcome.report.considered == 2
    assert any("page=2" in url for url in urls)
    assert all("/search" not in url for url in urls)
    assert any("state=closed" in url for url in urls)
    joined = "\n".join(urls)
    assert TOKEN not in joined


def test_limit_stops_before_the_next_page(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    urls: list[str] = []
    link = (
        "<https://api.github.com/repos/acme/widgets/pulls?state=closed&per_page=100&page=2>; "
        'rel="next"'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if request.url.path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        body = json.dumps([_pull(1, merged_at=None), _pull(2)])
        return httpx.Response(200, text=body, headers={"Link": link})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        outcome = run_funnel("acme/widgets", root=tmp_path, limit=1, client=client)
    assert outcome.report is not None
    assert outcome.report.considered == 1
    assert outcome.report.older_prs_cut_off is True
    assert not any("page=2" in url for url in urls)


def test_counts_add_up_and_large_pulls_skip_the_file_list(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    file_numbers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if path.endswith("/files"):
            number = path.rstrip("/").split("/")[-2]
            file_numbers.append(number)
            return httpx.Response(200, text=json.dumps(_files_for(int(number))))
        return httpx.Response(200, text=json.dumps(_sample_pulls()))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        outcome = run_funnel("acme/widgets", root=tmp_path, limit=20, client=client)
    assert outcome.report is not None
    report = outcome.report
    assert report.considered == 11
    assert report.accepted == 1
    assert report.counts.not_merged == 1
    assert report.counts.revert == 1
    assert report.counts.too_many_files == 1
    assert report.counts.too_many_lines == 1
    assert report.counts.unknown_size == 1
    assert report.counts.binary == 1
    assert report.counts.lockfile == 1
    assert report.counts.docs_only == 1
    assert report.counts.missing_source_or_test == 1
    assert report.counts.no_linked_issue == 1
    assert report.accepted + report.counts.total() == report.considered
    assert report.older_prs_cut_off is False
    assert "3" not in file_numbers
    assert "6" in file_numbers
    text = format_report(report)
    for reason in FilterReason:
        assert f"{reason.value} 1" in text
    assert "considered 11" in text
    assert "accepted 1" in text
    assert "older_prs_cut_off no" in text


def test_list_omits_size_so_the_pull_is_fetched_before_files(tmp_path: Path) -> None:
    """The list resource has no changed_files. The pull resource supplies it."""
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(request.url.path)
        path = request.url.path
        if path == "/repos/acme/widgets":
            return httpx.Response(200, text=repository_body("acme/widgets", "MIT"))
        if path == "/repos/acme/widgets/pulls/1":
            body = json.dumps(_pull(1, changed_files=6, additions=10, deletions=1))
            return httpx.Response(200, text=body)
        if path == "/repos/acme/widgets/pulls/2":
            body = json.dumps(_pull(2, changed_files=2, additions=4, deletions=1))
            return httpx.Response(200, text=body)
        if path == "/repos/acme/widgets/pulls/3":
            body = json.dumps(_pull(3, changed_files=1, additions=None, deletions=1))
            return httpx.Response(200, text=body)
        if path.endswith("/files"):
            return httpx.Response(200, text=json.dumps(_files_for(2)))
        listed = [
            _pull(1, changed_files=None, additions=None, deletions=None),
            _pull(2, changed_files=None, additions=None, deletions=None),
            _pull(3, changed_files=None, additions=None, deletions=None),
        ]
        return httpx.Response(200, text=json.dumps(listed))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        outcome = run_funnel("acme/widgets", root=tmp_path, limit=10, client=client)
    assert outcome.report is not None
    report = outcome.report
    assert report.considered == 3
    assert report.counts.too_many_files == 1
    assert report.counts.unknown_size == 1
    assert report.accepted == 1
    assert report.accepted + report.counts.total() == report.considered
    assert "/repos/acme/widgets/pulls/1" in urls
    assert "/repos/acme/widgets/pulls/2" in urls
    assert "/repos/acme/widgets/pulls/2/files" in urls
    assert "/repos/acme/widgets/pulls/1/files" not in urls
    assert "/repos/acme/widgets/pulls/3/files" not in urls
    assert all("/search" not in url for url in urls)
