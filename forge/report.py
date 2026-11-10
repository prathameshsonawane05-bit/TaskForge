"""Write one funnel as JSON and Markdown. Neither file is a score.

Precision and recall stay in the evaluation note. They are not written here.
"""

from __future__ import annotations

import json
from pathlib import Path

from forge.errors import ForgeError
from forge.funnel import format_report
from forge.models import FunnelReport, ReasonCode


def write_reports(report: FunnelReport, *, root: Path) -> tuple[Path, Path]:
    """Write both files, or neither when the counts do not add up."""
    if report.considered != report.accepted + report.counts.total():
        raise ForgeError(
            "Funnel counts do not add up to the pull requests that were read.",
            reason=ReasonCode.INTERNAL,
        )
    directory = root / "output" / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{_stem(report)}.json"
    markdown_path = directory / f"{_stem(report)}.md"
    json_path.write_text(render_json(report), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_json(report: FunnelReport) -> str:
    """Flat fields in the same order as the funnel text."""
    payload: dict[str, object] = {
        "repo": report.full_name,
        "limit": report.limit,
        "considered": report.considered,
    }
    payload.update(report.counts.model_dump())
    payload["accepted"] = report.accepted
    payload["older_prs_cut_off"] = _cut_off(report)
    return json.dumps(payload, indent=2) + "\n"


def render_markdown(report: FunnelReport) -> str:
    """The funnel text under a heading. The numbers are the JSON numbers."""
    return "# Funnel report\n\n" + format_report(report) + "\n"


def _stem(report: FunnelReport) -> str:
    owner, name = report.full_name.split("/", maxsplit=1)
    return f"{owner}-{name}-{report.limit}"


def _cut_off(report: FunnelReport) -> str:
    return "yes" if report.older_prs_cut_off else "no"
