"""Package a local fixture the gates have accepted.

The widget stays rejected. This sample has no upstream pull request, issue,
or SPDX license. Difficulty is an estimate and was not run against an agent.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from forge.errors import ForgeError
from forge.gates import GateReport, run_fixture_gates
from forge.models import ReasonCode
from forge.quality import QualityReport, check_quality, format_quality
from forge.sandbox import DEFAULT_TIMEOUT_SECONDS, Executor
from forge.widget_fixture import COUNTER_ISSUE

_ISSUES = {"counter": COUNTER_ISSUE}


@dataclass(frozen=True)
class PackageResult:
    report: GateReport
    quality: QualityReport | None
    directory: Path | None

    @property
    def written(self) -> bool:
        return self.directory is not None


def build_instruction(issue: str) -> str:
    """Turn the stored issue text into an instruction. Do not paste a solution."""
    body = issue.strip() + "\n"
    title = body.splitlines()[0].strip()
    return f"# {title}\n\n{body}"


def package_fixture(
    fixture: str,
    *,
    root: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
    host_platform: str | None = None,
) -> PackageResult:
    """Run the gates. Write a package only when they accept and V6 to V8 are clean."""
    report = run_fixture_gates(
        fixture,
        root=root,
        timeout=timeout,
        executor=executor,
        base_env=base_env,
        host_platform=host_platform,
    )
    if report.reason is not None:
        return PackageResult(report=report, quality=None, directory=None)
    issue = _ISSUES.get(fixture)
    if issue is None:
        raise ForgeError(
            "This fixture has no stored issue text.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    patches = root / "data" / "fixtures" / fixture / "patches"
    solution_patch = (patches / "solution.patch").read_text(encoding="utf-8")
    test_patch = (patches / "test.patch").read_text(encoding="utf-8")
    instruction = build_instruction(issue)
    fail_to_pass = report.runs[0].classification.fail_to_pass
    quality = check_quality(
        before_stdout=report.runs[0].before_stdout,
        fail_to_pass=fail_to_pass,
        instruction=instruction,
        solution_patch=solution_patch,
        test_patch=test_patch,
    )
    if not quality.clean:
        return PackageResult(report=report, quality=quality, directory=None)
    task_id = report.full_name.replace("/", "-")
    directory = root / "output" / "sample" / task_id
    if directory.exists():
        shutil.rmtree(directory)
    (directory / "solution").mkdir(parents=True)
    (directory / "tests").mkdir()
    (directory / "instruction.md").write_text(instruction, encoding="utf-8")
    (directory / "solution" / "solution.patch").write_text(solution_patch, encoding="utf-8")
    (directory / "tests" / "test.patch").write_text(test_patch, encoding="utf-8")
    pass_to_pass = report.runs[0].classification.pass_to_pass
    (directory / "tests" / "config.json").write_text(
        _json({"f2p": list(fail_to_pass), "p2p": list(pass_to_pass)}),
        encoding="utf-8",
    )
    (directory / "task.json").write_text(
        _json(_task(task_id, report)),
        encoding="utf-8",
    )
    (directory / "ATTRIBUTION.md").write_text(_attribution(report), encoding="utf-8")
    return PackageResult(report=report, quality=quality, directory=directory)


def format_package(result: PackageResult) -> str:
    reason = "none" if result.report.reason is None else result.report.reason.value
    lines = [
        f"repo {result.report.full_name}",
        f"commit {result.report.sha}",
        f"rejected {reason}",
    ]
    if result.directory is None:
        lines.append("packaged no")
    else:
        lines.append(f"packaged {result.directory}")
    if result.quality is not None:
        lines.append(format_quality(result.quality))
    return "\n".join(lines)


def _task(task_id: str, report: GateReport) -> dict[str, object]:
    run = report.runs[0]
    return {
        "task_id": task_id,
        "repo": report.full_name,
        "license": "no upstream",
        "pr_url": "no upstream",
        "issue_url": "no upstream",
        "base_commit": report.sha,
        "difficulty_signals": _DIFFICULTY,
        "f2p": list(run.classification.fail_to_pass),
        "p2p": list(run.classification.pass_to_pass),
        "tool_version": version("taskforge"),
    }


def _attribution(report: GateReport) -> str:
    return (
        "# Attribution\n\n"
        "This sample is a local fixture written to pass. There is no upstream.\n\n"
        f"- Repository: {report.full_name}. There is no upstream repository.\n"
        "- License: no upstream SPDX license.\n"
        "- Pull request: no upstream pull request.\n"
        "- Issue: no upstream issue.\n"
        f"- Base commit: {report.sha}\n\n"
        "Difficulty is an estimate. This task was not run against an agent.\n"
    )


_DIFFICULTY = "Difficulty is an estimate. This task was not run against an agent."


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2) + "\n"
