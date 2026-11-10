"""One fixture for each pull-request rejection, in filter order."""

import pytest

from forge.filters import classify_pull, decision_evidence, has_linked_issue, is_documentation
from forge.models import FilterReason, PullFilePayload, PullPayload


def _pull(**overrides: object) -> PullPayload:
    payload: dict[str, object] = {
        "number": 1,
        "title": "Handle empty input",
        "body": "Fixes #12",
        "merged_at": "2024-01-01T00:00:00Z",
        "changed_files": 2,
        "additions": 10,
        "deletions": 4,
    }
    payload.update(overrides)
    return PullPayload.model_validate(payload)


def _files(
    *names: str,
    binary: bool | None = None,
    patch: str | None = "@@\n+x\n",
) -> list[PullFilePayload]:
    return [
        PullFilePayload(filename=name, patch=patch, binary=binary if name == names[0] else None)
        for name in names
    ]


def _passing_files() -> list[PullFilePayload]:
    return _files("pkg/widget.py", "tests/test_widget.py")


def test_not_merged_wins_over_a_revert_title() -> None:
    reason = classify_pull(_pull(merged_at=None, title='Revert "Handle empty input"'), None)
    assert reason == FilterReason.NOT_MERGED


def test_revert() -> None:
    reason = classify_pull(_pull(title='Revert "Handle empty input"'), None)
    assert reason == FilterReason.REVERT


def test_too_many_files_does_not_need_the_file_list() -> None:
    reason = classify_pull(_pull(changed_files=6), None)
    assert reason == FilterReason.TOO_MANY_FILES


def test_five_files_is_not_too_many() -> None:
    files = _files(
        "pkg/a.py",
        "pkg/b.py",
        "pkg/c.py",
        "tests/test_a.py",
        "tests/test_b.py",
    )
    assert classify_pull(_pull(changed_files=5, additions=20, deletions=5), files) is None


def test_too_many_lines() -> None:
    reason = classify_pull(_pull(additions=200, deletions=101), None)
    assert reason == FilterReason.TOO_MANY_LINES


def test_three_hundred_lines_is_allowed() -> None:
    reason = classify_pull(_pull(additions=150, deletions=150), _passing_files())
    assert reason is None


def test_missing_additions_is_unknown_size_not_zero() -> None:
    reason = classify_pull(_pull(additions=None, deletions=0), None)
    assert reason == FilterReason.UNKNOWN_SIZE


def test_missing_changed_file_count_is_unknown_size() -> None:
    reason = classify_pull(_pull(changed_files=None, additions=1, deletions=1), None)
    assert reason == FilterReason.UNKNOWN_SIZE


def test_binary_extension() -> None:
    files = _files("assets/logo.png", "pkg/widget.py", "tests/test_widget.py")
    reason = classify_pull(_pull(changed_files=3), files)
    assert reason == FilterReason.BINARY


def test_explicit_binary_flag_without_a_known_suffix() -> None:
    files = [
        PullFilePayload(filename="data/blob.dat", patch=None, binary=True),
        PullFilePayload(filename="pkg/widget.py", patch="@@\n+x\n"),
        PullFilePayload(filename="tests/test_widget.py", patch="@@\n+y\n"),
    ]
    reason = classify_pull(_pull(changed_files=3), files)
    assert reason == FilterReason.BINARY


def test_missing_patch_on_a_python_file_is_not_binary() -> None:
    files = [
        PullFilePayload(filename="pkg/widget.py", patch=None),
        PullFilePayload(filename="tests/test_widget.py", patch=None),
    ]
    assert classify_pull(_pull(), files) is None


def test_lockfile() -> None:
    files = _files("pkg/widget.py", "tests/test_widget.py", "poetry.lock")
    reason = classify_pull(_pull(changed_files=3), files)
    assert reason == FilterReason.LOCKFILE


def test_docs_only() -> None:
    files = _files("README.md", "docs/guide.rst")
    reason = classify_pull(_pull(changed_files=2, additions=30, deletions=0), files)
    assert reason == FilterReason.DOCS_ONLY


def test_missing_source_or_test() -> None:
    reason = classify_pull(_pull(changed_files=1), _files("pkg/widget.py"))
    assert reason == FilterReason.MISSING_SOURCE_OR_TEST


def test_test_file_shapes() -> None:
    files = _files("pkg/widget.py", "pkg/widget_test.py")
    assert classify_pull(_pull(), files) is None
    files = _files("src/app.py", "conftest.py")
    assert classify_pull(_pull(), files) is None
    files = _files("pkg/widget.py", "tests/helpers.py")
    assert classify_pull(_pull(), files) is None


def test_no_linked_issue() -> None:
    pull = _pull(body="This changes the parser. See the discussion.")
    reason = classify_pull(pull, _passing_files())
    assert reason == FilterReason.NO_LINKED_ISSUE


def test_title_closing_keyword_does_not_count() -> None:
    pull = _pull(title="Fixes #12", body="No reference in the body.")
    assert classify_pull(pull, _passing_files()) == FilterReason.NO_LINKED_ISSUE


@pytest.mark.parametrize(
    "body",
    [
        "Closes #4",
        "closed #4",
        "close #4",
        "Fixes #9",
        "fixed #9",
        "fix #9",
        "Resolves #2",
        "resolved #2",
        "resolve #2",
        "This fixes acme/widgets#15.",
        "Fixes: #8",
    ],
)
def test_closing_keywords_link_an_issue(body: str) -> None:
    assert has_linked_issue(body)
    assert classify_pull(_pull(body=body), _passing_files()) is None


def test_keyword_and_issue_in_different_sentences_do_not_link() -> None:
    assert has_linked_issue("Please fix the parser.\n\nTracked as #44.") is False
    assert (
        has_linked_issue("Please fix the parser.\n\nSee https://github.com/acme/widgets/issues/44.")
        is False
    )


def test_issues_url_is_a_linked_issue() -> None:
    body = "Fixes https://github.com/acme/widgets/issues/15."
    assert has_linked_issue(body)
    assert classify_pull(_pull(body=body), _passing_files()) is None


def test_since_hash_is_not_a_closing_link() -> None:
    body = "Since #13714, the parser rejects empty input."
    assert has_linked_issue(body) is False
    assert classify_pull(_pull(body=body), _passing_files()) == FilterReason.NO_LINKED_ISSUE


def test_body_revert_does_not_need_a_revert_title() -> None:
    pull = _pull(body="This reverts commit abcdef.\n\nFixes #12")
    assert classify_pull(pull, None) == FilterReason.REVERT


def test_revert_phrase_in_the_title_only_is_not_a_body_revert() -> None:
    pull = _pull(title="This reverts commit abcdef", body="Fixes #12")
    assert classify_pull(pull, _passing_files()) is None


def test_unmerged_revert_body_is_not_merged() -> None:
    pull = _pull(merged_at=None, body="This reverts commit abcdef.")
    assert classify_pull(pull, None) == FilterReason.NOT_MERGED


def test_shorter_file_list_is_unknown_size() -> None:
    pull = _pull(changed_files=3)
    files = _passing_files()
    assert classify_pull(pull, files) is FilterReason.UNKNOWN_SIZE
    assert decision_evidence(pull, files) == "unknown_size files 2 changed_files 3"


def test_longer_file_list_does_not_accept_on_the_smaller_count() -> None:
    pull = _pull(changed_files=2)
    files = [
        *_passing_files(),
        PullFilePayload(filename="pkg/extra.py", patch="@@\n+x\n"),
    ]
    assert len(files) == 3
    assert classify_pull(pull, files) is FilterReason.UNKNOWN_SIZE
    assert decision_evidence(pull, files) == "unknown_size files 3 changed_files 2"


def test_length_mismatch_wins_over_a_later_binary_file() -> None:
    pull = _pull(changed_files=1)
    files = [
        PullFilePayload(filename="pkg/widget.py", patch="@@\n+x\n"),
        PullFilePayload(filename="assets/logo.png", patch=None),
    ]
    assert classify_pull(pull, files) is FilterReason.UNKNOWN_SIZE
    assert decision_evidence(pull, files).split()[0] == "unknown_size"


def test_file_payload_keeps_additions_and_deletions() -> None:
    item = PullFilePayload.model_validate(
        {"filename": "pkg/widget.py", "additions": 2, "deletions": 1}
    )
    assert item.additions == 2
    assert item.deletions == 1


def test_mixed_file_counts_are_unknown_size() -> None:
    pull = _pull(changed_files=2, additions=10, deletions=4)
    counted = PullFilePayload(
        filename="pkg/widget.py",
        patch="@@\n+x\n",
        additions=8,
        deletions=1,
    )
    missing = PullFilePayload(filename="tests/test_widget.py", patch="@@\n+x\n")
    assert classify_pull(pull, [counted, missing]) is FilterReason.UNKNOWN_SIZE
    assert decision_evidence(pull, [counted, missing]) == "unknown_size file counts incomplete"


def test_file_sum_mismatch_is_unknown_size_and_names_both_numbers() -> None:
    pull = _pull(changed_files=2, additions=10, deletions=4)
    files = [
        PullFilePayload(filename="pkg/widget.py", patch="@@\n+x\n", additions=1, deletions=1),
        PullFilePayload(
            filename="tests/test_widget.py",
            patch="@@\n+x\n",
            additions=1,
            deletions=1,
        ),
    ]
    assert classify_pull(pull, files) is FilterReason.UNKNOWN_SIZE
    assert decision_evidence(pull, files) == "unknown_size additions 2 10 deletions 2 4"


def test_matching_file_sums_still_use_later_filters() -> None:
    pull = _pull(changed_files=2, additions=10, deletions=4)
    files = [
        PullFilePayload(filename="pkg/widget.py", patch="@@\n+x\n", additions=8, deletions=1),
        PullFilePayload(
            filename="tests/test_widget.py",
            patch="@@\n+x\n",
            additions=2,
            deletions=3,
        ),
    ]
    assert classify_pull(pull, files) is None
    assert decision_evidence(pull, files) == "accepted issue 12"


def test_omitted_file_counts_keep_the_pull_totals() -> None:
    pull = _pull(changed_files=2, additions=10, deletions=4)
    assert classify_pull(pull, _passing_files()) is None
    assert decision_evidence(pull, _passing_files()) == "accepted issue 12"


def test_decision_evidence_names_the_first_binary_lockfile_and_docs_file() -> None:
    binary = _pull(changed_files=3)
    binary_files = [
        PullFilePayload(filename="notes.md", patch="@@\n+x\n"),
        PullFilePayload(filename="assets/logo.png", patch=None),
        PullFilePayload(filename="assets/icon.png", patch=None),
    ]
    assert classify_pull(binary, binary_files) is FilterReason.BINARY
    assert decision_evidence(binary, binary_files) == "binary assets/logo.png"

    locked = _pull()
    locked_files = [
        PullFilePayload(filename="pkg/widget.py", patch="@@\n+x\n"),
        PullFilePayload(filename="poetry.lock", patch="@@\n+x\n"),
    ]
    assert classify_pull(locked, locked_files) is FilterReason.LOCKFILE
    assert decision_evidence(locked, locked_files) == "lockfile poetry.lock"

    docs = _pull(changed_files=2)
    docs_files = _files("README.md", "docs/guide.rst")
    assert classify_pull(docs, docs_files) is FilterReason.DOCS_ONLY
    assert decision_evidence(docs, docs_files) == "docs_only README.md"


def test_requirements_txt_stays_documentation() -> None:
    assert is_documentation("requirements.txt") is True
    pull = _pull(changed_files=1)
    files = _files("requirements.txt")
    assert classify_pull(pull, files) is FilterReason.DOCS_ONLY
    assert decision_evidence(pull, files) == "docs_only requirements.txt"


def test_decision_evidence_matches_classify_pull() -> None:
    cases: list[tuple[PullPayload, list[PullFilePayload] | None]] = [
        (_pull(merged_at=None), None),
        (_pull(title="Revert the widget"), _passing_files()),
        (_pull(changed_files=None), None),
        (_pull(changed_files=6), None),
        (_pull(additions=None), None),
        (_pull(additions=301, deletions=0), None),
        (_pull(), _files("assets/logo.png")),
        (_pull(), _files("uv.lock")),
        (_pull(), _files("README.md")),
        (_pull(), _files("pkg/widget.py")),
        (_pull(body="See the discussion."), _passing_files()),
        (_pull(), _passing_files()),
    ]
    for pull, files in cases:
        reason = classify_pull(pull, files)
        text = decision_evidence(pull, files)
        expected = "accepted" if reason is None else reason.value
        assert text.split()[0] == expected
