"""Package a local fixture the gates have accepted.

The widget stays rejected. This sample has no upstream pull request, issue,
or SPDX license. Difficulty is an estimate and was not run against an agent.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from forge.check import check_repository
from forge.config import default_cache_path, load_github_token
from forge.errors import ForgeError, GitHubError
from forge.gates import (
    GATE_RUNTIME_LIMIT_SECONDS,
    GateReason,
    GateReport,
    GateRun,
    _early_reason,
    _gate_run,
    first_reason,
    run_fixture_gates,
)
from forge.github import API_ROOT, GitHubClient
from forge.models import CheckResult, FilterReason, ReasonCode
from forge.outcomes import run_trial_container
from forge.quality import QualityReport, check_quality, format_quality
from forge.sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    Executor,
    _checkout,
    _prepared_env,
    build_eval_image,
    default_executor,
    image_tag,
)
from forge.split import SplitReport, run_split
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


@dataclass(frozen=True)
class PullPackageResult:
    full_name: str
    number: int
    repo_refusal: CheckResult | None = None
    filter_reason: FilterReason | None = None
    package_reason: str | None = None
    report: GateReport | None = None
    quality: QualityReport | None = None
    directory: Path | None = None
    spdx_id: str | None = None

    @property
    def written(self) -> bool:
        return self.directory is not None


def package_pull(
    repo: str,
    number: int,
    *,
    root: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    client: GitHubClient | None = None,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
    host_platform: str | None = None,
) -> PullPackageResult:
    """Package one pull request. A filter rejection writes no files."""
    gate = check_repository(repo, root=root, client=client)
    if not gate.accepted:
        return PullPackageResult(
            full_name=gate.full_name,
            number=number,
            repo_refusal=gate,
            spdx_id=gate.spdx_id,
        )
    if client is not None:
        return _package_accepted(
            gate,
            number,
            root=root,
            client=client,
            timeout=timeout,
            executor=executor,
            base_env=base_env,
            host_platform=host_platform,
        )
    token = load_github_token(root / ".env")
    with GitHubClient(token=token, cache_path=default_cache_path(root)) as owned:
        return _package_accepted(
            gate,
            number,
            root=root,
            client=owned,
            timeout=timeout,
            executor=executor,
            base_env=base_env,
            host_platform=host_platform,
        )


def format_pull_package(result: PullPackageResult) -> str:
    if result.repo_refusal is not None:
        return _refused_line(result.full_name, result.number, result.repo_refusal)
    if result.filter_reason is not None:
        return f"refused {result.full_name}#{result.number} reason={result.filter_reason.value}"
    if result.package_reason is not None:
        return f"refused {result.full_name}#{result.number} reason={result.package_reason}"
    report = result.report
    if report is None:
        raise ForgeError(
            "Pull package finished without a gate report.",
            reason=ReasonCode.INTERNAL,
        )
    reason = "none" if report.reason is None else report.reason.value
    lines = [
        f"repo {report.full_name}",
        f"pull {result.number}",
        f"commit {report.sha}",
        f"image {report.image}",
        f"limit_seconds {report.limit_seconds:g}",
        f"runs {len(report.runs)}",
        f"rejected {reason}",
    ]
    for index, run in enumerate(report.runs, start=1):
        lines.extend(_run_counts(index, run))
    if report.runs:
        elapsed = sum(run.elapsed for run in report.runs)
        lines.append(f"total_elapsed {elapsed:.3f}")
    if result.directory is None:
        lines.append("packaged no")
    else:
        lines.append(f"packaged {result.directory}")
    if result.quality is not None:
        lines.append(format_quality(result.quality))
    return "\n".join(lines)


def _package_accepted(
    gate: CheckResult,
    number: int,
    *,
    root: Path,
    client: GitHubClient,
    timeout: float,
    executor: Executor | None,
    base_env: Mapping[str, str] | None,
    host_platform: str | None,
) -> PullPackageResult:
    split = run_split(gate.full_name, number, root=root, client=client)
    if split.filter_reason is not None or split.report is None:
        reason = split.filter_reason
        if reason is None:
            raise ForgeError(
                "Accepted repository produced no pull report.",
                reason=ReasonCode.INTERNAL,
            )
        if reason in {FilterReason.BINARY, FilterReason.LOCKFILE}:
            return PullPackageResult(
                full_name=gate.full_name,
                number=number,
                package_reason="unsupported_file",
                spdx_id=gate.spdx_id,
            )
        return PullPackageResult(
            full_name=gate.full_name,
            number=number,
            filter_reason=reason,
            spdx_id=gate.spdx_id,
        )
    if split.report.unsupported_files:
        return PullPackageResult(
            full_name=gate.full_name,
            number=number,
            package_reason="unsupported_file",
            spdx_id=gate.spdx_id,
        )
    owner, name = gate.full_name.split("/", maxsplit=1)
    base, _merge, head = _merge_parent(client, owner, name, number)
    patches = _write_patches(root, owner, name, number, split.report)
    env = _prepared_env(root, base_env)
    checkout_run = executor if executor is not None else default_executor
    checkout = _checkout(owner, name, base, root, checkout_run, env)
    tag = image_tag(owner, name, base)
    try:
        image = build_eval_image(
            owner,
            name,
            base,
            checkout,
            root=root,
            executor=executor,
            base_env=base_env,
            host_platform=host_platform,
        )
    except ForgeError as exc:
        if exc.reason == ReasonCode.SANDBOX_ERROR and str(exc) == "docker build failed.":
            return PullPackageResult(
                full_name=gate.full_name,
                number=number,
                report=_empty_gate(gate.full_name, base, tag, GateReason.BUILD_FAILED),
                spdx_id=gate.spdx_id,
            )
        raise
    runs = []
    for index in range(3):
        started = time.perf_counter()
        trial = run_trial_container(
            full_name=gate.full_name,
            sha=base,
            image=image,
            patches=patches,
            checkout=checkout,
            root=root,
            timeout=timeout,
            executor=executor,
            base_env=base_env,
        )
        runs.append(_gate_run(trial, time.perf_counter() - started))
        if index == 0:
            early = _early_reason(runs[0])
            if early is not None:
                return PullPackageResult(
                    full_name=gate.full_name,
                    number=number,
                    report=_gate_report(gate.full_name, base, image, early, (runs[0],)),
                    spdx_id=gate.spdx_id,
                )
    observed = tuple(runs)
    gate_reason = first_reason(
        observed,
        build_ok=True,
        limit_seconds=GATE_RUNTIME_LIMIT_SECONDS,
    )
    report = _gate_report(gate.full_name, base, image, gate_reason, observed)
    if gate_reason is not None:
        return PullPackageResult(
            full_name=gate.full_name,
            number=number,
            report=report,
            spdx_id=gate.spdx_id,
        )
    instruction = build_instruction(
        split.report.issue_title + "\n\n" + (split.report.issue_body or "")
    )
    quality = check_quality(
        before_stdout=observed[0].before_stdout,
        fail_to_pass=observed[0].classification.fail_to_pass,
        instruction=instruction,
        solution_patch=split.report.source_patch,
        test_patch=split.report.test_patch,
    )
    if not quality.clean:
        return PullPackageResult(
            full_name=gate.full_name,
            number=number,
            report=report,
            quality=quality,
            spdx_id=gate.spdx_id,
        )
    directory = _write_pull_package(
        root=root,
        owner=owner,
        name=name,
        number=number,
        spdx=gate.spdx_id or "",
        issue_url=split.report.issue_url,
        base=base,
        merge=_merge,
        head=head,
        instruction=instruction,
        source_patch=split.report.source_patch,
        test_patch=split.report.test_patch,
        fail_to_pass=observed[0].classification.fail_to_pass,
        pass_to_pass=observed[0].classification.pass_to_pass,
    )
    return PullPackageResult(
        full_name=gate.full_name,
        number=number,
        report=report,
        quality=quality,
        directory=directory,
        spdx_id=gate.spdx_id,
    )


def _merge_parent(
    client: GitHubClient,
    owner: str,
    name: str,
    number: int,
) -> tuple[str, str, str]:
    pull = client.get(f"{API_ROOT}/repos/{owner}/{name}/pulls/{number}")
    if not isinstance(pull.data, dict):
        raise GitHubError(
            "Pull request payload was not a JSON object.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    merge = pull.data.get("merge_commit_sha")
    if not isinstance(merge, str) or not merge:
        raise GitHubError(
            "Pull request has no merge commit.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    head_obj = pull.data.get("head")
    head = ""
    if isinstance(head_obj, dict) and isinstance(head_obj.get("sha"), str):
        head = head_obj["sha"]
    commit = client.get(f"{API_ROOT}/repos/{owner}/{name}/commits/{merge}")
    if not isinstance(commit.data, dict):
        raise GitHubError(
            "Commit payload was not a JSON object.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    parents = commit.data.get("parents")
    if not isinstance(parents, list) or not parents or not isinstance(parents[0], dict):
        raise GitHubError(
            "Merge commit had no first parent.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    parent = parents[0].get("sha")
    if not isinstance(parent, str) or not parent:
        raise GitHubError(
            "Merge commit had no first parent.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return parent, merge, head


def _write_patches(
    root: Path,
    owner: str,
    name: str,
    number: int,
    report: SplitReport,
) -> Path:
    patches = root / "data" / "packages" / owner / name / str(number) / "patches"
    patches.mkdir(parents=True, exist_ok=True)
    (patches / "solution.patch").write_text(report.source_patch, encoding="utf-8")
    (patches / "test.patch").write_text(report.test_patch, encoding="utf-8")
    return patches


def _write_pull_package(
    *,
    root: Path,
    owner: str,
    name: str,
    number: int,
    spdx: str,
    issue_url: str,
    base: str,
    merge: str,
    head: str,
    instruction: str,
    source_patch: str,
    test_patch: str,
    fail_to_pass: tuple[str, ...],
    pass_to_pass: tuple[str, ...],
) -> Path:
    task_id = f"{owner}-{name}-{number}"
    directory = root / "output" / task_id
    if directory.exists():
        shutil.rmtree(directory)
    (directory / "solution").mkdir(parents=True)
    (directory / "tests").mkdir()
    (directory / "instruction.md").write_text(instruction, encoding="utf-8")
    (directory / "solution" / "solution.patch").write_text(source_patch, encoding="utf-8")
    (directory / "tests" / "test.patch").write_text(test_patch, encoding="utf-8")
    (directory / "tests" / "config.json").write_text(
        _json({"f2p": list(fail_to_pass), "p2p": list(pass_to_pass)}),
        encoding="utf-8",
    )
    (directory / "task.json").write_text(
        _json(
            {
                "task_id": task_id,
                "repo": f"{owner}/{name}",
                "license": spdx,
                "pr_url": f"https://github.com/{owner}/{name}/pull/{number}",
                "issue_url": issue_url,
                "base_commit": base,
                "difficulty_signals": _DIFFICULTY,
                "f2p": list(fail_to_pass),
                "p2p": list(pass_to_pass),
                "tool_version": version("taskforge"),
            }
        ),
        encoding="utf-8",
    )
    shas = [f"- Base commit: {base}", f"- Merge commit: {merge}"]
    if head:
        shas.append(f"- Head commit: {head}")
    attribution = (
        "# Attribution\n\n"
        f"- Repository: {owner}/{name}\n"
        f"- License: {spdx}\n"
        f"- Pull request: https://github.com/{owner}/{name}/pull/{number}\n"
        f"- Issue: {issue_url}\n"
        + "\n".join(shas)
        + f"\n\n{_DIFFICULTY}\n"
    )
    (directory / "ATTRIBUTION.md").write_text(attribution, encoding="utf-8")
    return directory


def _empty_gate(full_name: str, sha: str, image: str, reason: GateReason) -> GateReport:
    return _gate_report(full_name, sha, image, reason, ())


def _gate_report(
    full_name: str,
    sha: str,
    image: str,
    reason: GateReason | None,
    runs: tuple[GateRun, ...],
) -> GateReport:
    return GateReport(
        full_name=full_name,
        sha=sha,
        image=image,
        reason=reason,
        runs=runs,
        limit_seconds=GATE_RUNTIME_LIMIT_SECONDS,
    )


def _run_counts(index: int, run: GateRun) -> list[str]:
    grouped = run.classification
    lines = [
        (
            f"run {index} elapsed {run.elapsed:.3f} "
            f"before {run.before_status} after {run.after_status}"
        ),
        (
            f"run {index} f2p {len(grouped.fail_to_pass)} "
            f"p2p {len(grouped.pass_to_pass)} "
            f"still {len(grouped.still_failing)} "
            f"regression {len(grouped.regression)} "
            f"skipped {len(grouped.skipped)}"
        ),
    ]
    for label, ids in (
        ("f2p", grouped.fail_to_pass),
        ("still", grouped.still_failing),
        ("regression", grouped.regression),
        ("skipped", grouped.skipped),
    ):
        lines.extend(f"  {label} {test_id}" for test_id in ids)
    return lines


def _refused_line(full_name: str, number: int, gate: CheckResult) -> str:
    reason = gate.reason if gate.reason is not None else ReasonCode.INTERNAL
    if gate.spdx_id is None:
        return f"refused {full_name}#{number} reason={reason}"
    return f"refused {full_name}#{number} reason={reason} spdx={gate.spdx_id}"
