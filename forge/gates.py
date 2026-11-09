"""Validation gates. The first failing gate is the only reject reason.

A single classified run is not one of these gates. Fail-to-pass is not
checked by asking whether those same tests passed: that check cannot fail.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from forge.errors import ForgeError
from forge.models import ReasonCode
from forge.outcomes import (
    Classification,
    TrialReport,
    run_trial_container,
)
from forge.sandbox import (
    DEFAULT_MEMORY,
    DEFAULT_TIMEOUT_SECONDS,
    Executor,
    build_eval_image,
    image_tag,
)
from forge.widget_fixture import prepare_counter, prepare_widget

# Chosen before any stage 6 gate run. The sum of the three container
# runtimes is too slow when it is over this many seconds.
GATE_RUNTIME_LIMIT_SECONDS = 30.0


class GateReason(StrEnum):
    """One reject reason. The gates are checked in this order."""

    BUILD_FAILED = "build_failed"
    NO_FAILURE_BEFORE = "no_failure_before"
    NO_FAIL_TO_PASS = "no_fail_to_pass"
    REGRESSION = "regression"
    FLAKY = "flaky"
    TOO_SLOW = "too_slow"


@dataclass(frozen=True)
class GateRun:
    classification: Classification
    before_status: int
    after_status: int
    failed_before: tuple[str, ...]
    elapsed: float


@dataclass(frozen=True)
class GateReport:
    full_name: str
    sha: str
    image: str
    reason: GateReason | None
    runs: tuple[GateRun, ...]
    limit_seconds: float


def first_reason(
    runs: Sequence[GateRun],
    *,
    build_ok: bool,
    limit_seconds: float,
) -> GateReason | None:
    """Return the first failing gate, or None when every gate passes."""
    if not build_ok:
        return GateReason.BUILD_FAILED
    if not runs:
        raise ForgeError(
            "A built image needs a run before the later gates.",
            reason=ReasonCode.INTERNAL,
        )
    early = _early_reason(runs[0])
    if early is not None:
        return early
    if len(runs) != 3:
        raise ForgeError(
            "Three runs are required once the early gates pass.",
            reason=ReasonCode.INTERNAL,
        )
    if not _runs_match(runs):
        return GateReason.FLAKY
    if sum(run.elapsed for run in runs) > limit_seconds:
        return GateReason.TOO_SLOW
    return None


def run_fixture_gates(
    fixture: str,
    *,
    root: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
    host_platform: str | None = None,
    limit_seconds: float = GATE_RUNTIME_LIMIT_SECONDS,
) -> GateReport:
    """Run the gates on one local fixture. Local fixtures skip the allowlist."""
    if fixture == "widget":
        prepared = prepare_widget(root)
        owner, name = "local", "widget"
    elif fixture == "counter":
        prepared = prepare_counter(root)
        owner, name = "local", "counter"
    else:
        raise ForgeError(
            "Fixture must be widget or counter.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    full_name = f"{owner}/{name}"
    tag = image_tag(owner, name, prepared.sha)
    try:
        image = build_eval_image(
            owner,
            name,
            prepared.sha,
            prepared.checkout,
            root=root,
            executor=executor,
            base_env=base_env,
            host_platform=host_platform,
        )
    except ForgeError as exc:
        if exc.reason == ReasonCode.SANDBOX_ERROR and str(exc) == "docker build failed.":
            return GateReport(
                full_name=full_name,
                sha=prepared.sha,
                image=tag,
                reason=GateReason.BUILD_FAILED,
                runs=(),
                limit_seconds=limit_seconds,
            )
        raise
    runs: list[GateRun] = []
    for index in range(3):
        started = time.perf_counter()
        report = run_trial_container(
            full_name=full_name,
            sha=prepared.sha,
            image=image,
            patches=prepared.patches,
            checkout=prepared.checkout,
            root=root,
            timeout=timeout,
            executor=executor,
            base_env=base_env,
        )
        runs.append(_gate_run(report, time.perf_counter() - started))
        if index == 0:
            early = _early_reason(runs[0])
            if early is not None:
                return GateReport(
                    full_name=full_name,
                    sha=prepared.sha,
                    image=image,
                    reason=early,
                    runs=(runs[0],),
                    limit_seconds=limit_seconds,
                )
    observed = tuple(runs)
    return GateReport(
        full_name=full_name,
        sha=prepared.sha,
        image=image,
        reason=first_reason(observed, build_ok=True, limit_seconds=limit_seconds),
        runs=observed,
        limit_seconds=limit_seconds,
    )


def format_gates(report: GateReport) -> str:
    reason = "none" if report.reason is None else report.reason.value
    lines = [
        f"repo {report.full_name}",
        f"commit {report.sha}",
        f"image {report.image}",
        f"memory {DEFAULT_MEMORY}",
        f"limit_seconds {report.limit_seconds:g}",
        f"runs {len(report.runs)}",
        f"rejected {reason}",
    ]
    for index, run in enumerate(report.runs, start=1):
        lines.append(f"run {index} elapsed {run.elapsed:.3f}")
        lines.append(f"run {index} before_pytest {run.before_status}")
        lines.append(f"run {index} after_pytest {run.after_status}")
        groups = (
            ("fail_to_pass", run.classification.fail_to_pass),
            ("pass_to_pass", run.classification.pass_to_pass),
            ("still_failing", run.classification.still_failing),
            ("regression", run.classification.regression),
            ("skipped", run.classification.skipped),
        )
        for name, ids in groups:
            lines.append(f"run {index} {name} {len(ids)}")
            lines.extend(f"  {test_id}" for test_id in ids)
    if report.runs:
        lines.append(f"total_elapsed {sum(run.elapsed for run in report.runs):.3f}")
    if report.reason is None and report.full_name == "local/counter":
        lines.append(
            "note This project was written to pass, so three matching runs "
            "are weak evidence about real flakes."
        )
    return "\n".join(lines)


def _early_reason(run: GateRun) -> GateReason | None:
    if not run.failed_before:
        return GateReason.NO_FAILURE_BEFORE
    if not run.classification.fail_to_pass:
        return GateReason.NO_FAIL_TO_PASS
    if run.classification.regression:
        return GateReason.REGRESSION
    return None


def _runs_match(runs: Sequence[GateRun]) -> bool:
    first = runs[0]
    return all(
        run.classification == first.classification
        and run.before_status == first.before_status
        and run.after_status == first.after_status
        for run in runs[1:]
    )


def _gate_run(report: TrialReport, elapsed: float) -> GateRun:
    return GateRun(
        classification=report.classification,
        before_status=report.before_status,
        after_status=report.after_status,
        failed_before=report.failed_before,
        elapsed=elapsed,
    )
