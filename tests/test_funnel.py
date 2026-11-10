"""Funnel pagination and the rule that rejection counts add up."""

import json
from pathlib import Path

import httpx

from forge.funnel import collect_closed_pulls, format_report, run_funnel
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
    assert "order created desc" in text
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


def test_list_url_asks_for_created_descending(tmp_path: Path) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, text=json.dumps([_pull(1)]))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        collect_closed_pulls(client, "acme", "widgets", 5)
    assert len(urls) == 1
    assert "sort=created" in urls[0]
    assert "direction=desc" in urls[0]
    assert "state=closed" in urls[0]


def test_two_pages_keep_fixture_order_when_closed_at_runs_backward(tmp_path: Path) -> None:
    link = (
        "<https://api.github.com/repos/acme/widgets/pulls"
        "?state=closed&sort=created&direction=desc&per_page=100&page=2>; "
        'rel="next"'
    )
    page_one = [
        _pull(10, created_at="2024-02-01T00:00:00Z", closed_at="2020-01-01T00:00:00Z"),
        _pull(8, created_at="2024-01-01T00:00:00Z", closed_at="2020-06-01T00:00:00Z"),
    ]
    page_two = [
        _pull(4, created_at="2023-01-01T00:00:00Z", closed_at="2024-12-01T00:00:00Z"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if "page=2" in str(request.url):
            return httpx.Response(200, text=json.dumps(page_two))
        return httpx.Response(200, text=json.dumps(page_one), headers={"Link": link})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        pulls, _cut_off = collect_closed_pulls(client, "acme", "widgets", 10)
    assert [pull.number for pull in pulls] == [10, 8, 4]
    assert [pull.closed_at for pull in pulls] == [
        "2020-01-01T00:00:00Z",
        "2020-06-01T00:00:00Z",
        "2024-12-01T00:00:00Z",
    ]


def test_equal_created_at_stays_in_fixture_order(tmp_path: Path) -> None:
    listed = [
        _pull(7, created_at="2020-05-01T00:00:00Z", closed_at="2020-05-02T00:00:00Z"),
        _pull(2, created_at="2020-05-01T00:00:00Z", closed_at="2020-05-03T00:00:00Z"),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps(listed))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        pulls, _cut_off = collect_closed_pulls(client, "acme", "widgets", 10)
    assert [pull.number for pull in pulls] == [7, 2]
    assert pulls[0].created_at == pulls[1].created_at


def test_link_next_page_three_is_requested_and_page_two_is_not(tmp_path: Path) -> None:
    urls: list[str] = []
    link = (
        "<https://api.github.com/repos/acme/widgets/pulls"
        "?state=closed&sort=created&direction=desc&per_page=100&page=3>; "
        'rel="next"'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if "page=3" in str(request.url):
            return httpx.Response(200, text=json.dumps([_pull(5)]))
        return httpx.Response(200, text=json.dumps([_pull(9)]), headers={"Link": link})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        pulls, _cut_off = collect_closed_pulls(client, "acme", "widgets", 10)
    assert [pull.number for pull in pulls] == [9, 5]
    assert any("page=3" in url for url in urls)
    assert not any("page=2" in url for url in urls)


def test_the_same_fixture_returns_the_same_order_twice(tmp_path: Path) -> None:
    listed = [
        _pull(7, created_at="2020-05-01T00:00:00Z"),
        _pull(2, created_at="2020-05-01T00:00:00Z"),
        _pull(9, created_at="2020-04-01T00:00:00Z"),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps(listed), headers={"ETag": '"fixed"'})

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        first, _cut_off = collect_closed_pulls(client, "acme", "widgets", 10)
        second, _again = collect_closed_pulls(client, "acme", "widgets", 10)
    assert [pull.number for pull in first] == [7, 2, 9]
    assert [pull.number for pull in second] == [7, 2, 9]


def test_rate_limit_retry_returns_the_successful_list_order(tmp_path: Path) -> None:
    attempts = {"list": 0}
    listed = [
        _pull(4, created_at="2021-01-02T00:00:00Z", closed_at="2020-01-01T00:00:00Z"),
        _pull(1, created_at="2021-01-01T00:00:00Z", closed_at="2021-06-01T00:00:00Z"),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["list"] += 1
        if attempts["list"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, text=json.dumps(listed))

    with make_client(
        TOKEN,
        tmp_path / "cache.sqlite",
        handler,
        sleeper=lambda _delay: None,
    ) as client:
        pulls, _cut_off = collect_closed_pulls(client, "acme", "widgets", 10)
    assert attempts["list"] == 2
    assert [pull.number for pull in pulls] == [4, 1]
