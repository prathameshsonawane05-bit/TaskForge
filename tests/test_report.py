"""Report files are rendered from a FunnelReport. These tests do not use the network."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forge.cli import app
from forge.errors import ForgeError
from forge.models import FunnelCounts, FunnelReport, ReasonCode
from forge.report import write_reports
from tests.fakes import write_project

runner = CliRunner()


def _report(*, considered: int, accepted: int, not_merged: int) -> FunnelReport:
    return FunnelReport(
        full_name="pallets/itsdangerous",
        limit=40,
        considered=considered,
        counts=FunnelCounts(
            not_merged=not_merged,
            too_many_files=3,
            docs_only=3,
            missing_source_or_test=8,
        ),
        accepted=accepted,
        older_prs_cut_off=True,
    )


def test_mismatched_counts_write_neither_file(tmp_path: Path) -> None:
    reports = tmp_path / "output" / "reports"
    reports.mkdir(parents=True)
    with pytest.raises(ForgeError) as caught:
        write_reports(_report(considered=40, accepted=0, not_merged=25), root=tmp_path)
    assert caught.value.reason == ReasonCode.INTERNAL
    assert list(reports.iterdir()) == []


def test_json_and_markdown_contain_the_same_numbers(tmp_path: Path) -> None:
    json_path, markdown_path = write_reports(
        _report(considered=40, accepted=0, not_merged=26),
        root=tmp_path,
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    text = markdown_path.read_text(encoding="utf-8")
    assert "precision" not in text.casefold()
    assert "recall" not in text.casefold()
    assert "precision" not in json_path.read_text(encoding="utf-8")
    assert "recall" not in json_path.read_text(encoding="utf-8")
    numbers = {
        "limit": 40,
        "considered": 40,
        "not_merged": 26,
        "revert": 0,
        "too_many_files": 3,
        "too_many_lines": 0,
        "unknown_size": 0,
        "binary": 0,
        "lockfile": 0,
        "docs_only": 3,
        "missing_source_or_test": 8,
        "no_linked_issue": 0,
        "accepted": 0,
    }
    for name, value in numbers.items():
        assert payload[name] == value
        assert f"{name} {value}" in text
    assert payload["repo"] == "pallets/itsdangerous"
    assert payload["order"] == "created desc"
    assert "order created desc" in text
    assert payload["older_prs_cut_off"] == "yes"
    assert "older_prs_cut_off yes" in text
    assert "repo pallets/itsdangerous" in text


def test_a_refused_repository_writes_neither_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project(tmp_path, "GITHUB_TOKEN=\n", ["acme/widgets"])
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report", "torvalds/linux", "--limit", "40"])
    assert result.exit_code == 1
    assert "refused torvalds/linux reason=not_on_allowlist" in result.stdout
    assert not (tmp_path / "output").exists()
