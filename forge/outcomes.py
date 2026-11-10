"""Classify tests run before and after a solution. One pair of runs is not a gate."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from forge.errors import ForgeError
from forge.models import ReasonCode
from forge.sandbox import (
    DEFAULT_MEMORY,
    DEFAULT_TIMEOUT_SECONDS,
    Executor,
    SandboxSuccess,
    build_eval_image,
    run_mounted,
)
from forge.widget_fixture import prepare_widget

_RESULT = re.compile(
    r"^(?P<id>\S+::\S+)\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b"
)
_PASS_WORDS = frozenset({"PASSED", "XPASS"})

TRIAL_SCRIPT = """\
cd /repo || exit 3
export PYTHONPATH=/repo
git -c safe.directory=/repo apply --check /patches/solution.patch || exit 4
echo SOLUTION_CHECK:absent
git -c safe.directory=/repo apply /patches/test.patch || exit 5
python -m pytest -p no:cacheprovider --tb=line -v > /tmp/before.txt 2> /tmp/before.err
echo BEFORE_STATUS:$?
git -c safe.directory=/repo apply /patches/solution.patch || exit 6
python -m pytest -p no:cacheprovider --tb=line -v > /tmp/after.txt 2> /tmp/after.err
echo AFTER_STATUS:$?
echo ---BEFORE-STDOUT---
cat /tmp/before.txt
echo ---BEFORE-STDERR---
cat /tmp/before.err
echo ---AFTER-STDOUT---
cat /tmp/after.txt
echo ---AFTER-STDERR---
cat /tmp/after.err
"""


@dataclass(frozen=True)
class Classification:
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    still_failing: tuple[str, ...]
    regression: tuple[str, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class TrialReport:
    full_name: str
    sha: str
    image: str
    container_exit: int
    before_status: int
    after_status: int
    classification: Classification
    failed_before: tuple[str, ...]
    before_stdout: str
    before_stderr: str
    after_stdout: str
    after_stderr: str
    trial_stdout: str


def parse_pytest_verbose(text: str) -> dict[str, str]:
    """Map each verbose result line to pass, fail, or skip. A skip is not a pass."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _RESULT.match(line.strip())
        if match is None:
            continue
        word = match.group("status")
        if word in _PASS_WORDS:
            status = "pass"
        elif word == "SKIPPED":
            status = "skip"
        else:
            status = "fail"
        found[match.group("id")] = status
    return found


def classify(before: Mapping[str, str], after: Mapping[str, str]) -> Classification:
    """Bucket every id that ran.

    A skip in either run is skipped. It is not still failing, and a skip
    that later passes is not fail-to-pass. Only ``pass`` counts as a pass.
    """
    fail_to_pass: list[str] = []
    pass_to_pass: list[str] = []
    still_failing: list[str] = []
    regression: list[str] = []
    skipped: list[str] = []
    ids = sorted(set(before) | set(after))
    for test_id in ids:
        left = before.get(test_id)
        right = after.get(test_id)
        if left == "skip" or right == "skip":
            skipped.append(test_id)
        elif left != "pass" and right == "pass":
            fail_to_pass.append(test_id)
        elif left == "pass" and right == "pass":
            pass_to_pass.append(test_id)
        elif left == "pass" and right != "pass":
            regression.append(test_id)
        else:
            still_failing.append(test_id)
    result = Classification(
        fail_to_pass=tuple(fail_to_pass),
        pass_to_pass=tuple(pass_to_pass),
        still_failing=tuple(still_failing),
        regression=tuple(regression),
        skipped=tuple(skipped),
    )
    total = (
        len(result.fail_to_pass)
        + len(result.pass_to_pass)
        + len(result.still_failing)
        + len(result.regression)
        + len(result.skipped)
    )
    if total != len(ids):
        raise ForgeError(
            "Outcome buckets do not add up to the tests that ran.",
            reason=ReasonCode.INTERNAL,
        )
    return result


def run_trial_container(
    *,
    full_name: str,
    sha: str,
    image: str,
    patches: Path,
    checkout: Path,
    root: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
) -> TrialReport:
    """Apply both patches inside one fresh container and classify the two pytest runs."""
    outcome = run_mounted(
        full_name=full_name,
        sha=sha,
        image=image,
        command=["sh", "-c", TRIAL_SCRIPT],
        mount=patches,
        checkout=checkout,
        root=root,
        timeout=timeout,
        executor=executor,
        base_env=base_env,
    )
    return _report(outcome, image=image)


def run_widget_trial(
    *,
    root: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
    host_platform: str | None = None,
) -> TrialReport:
    """Apply both patches inside one container and classify the two pytest runs."""
    prepared = prepare_widget(root)
    image = build_eval_image(
        "local",
        "widget",
        prepared.sha,
        prepared.checkout,
        root=root,
        executor=executor,
        base_env=base_env,
        host_platform=host_platform,
    )
    return run_trial_container(
        full_name="local/widget",
        sha=prepared.sha,
        image=image,
        patches=prepared.patches,
        checkout=prepared.checkout,
        root=root,
        timeout=timeout,
        executor=executor,
        base_env=base_env,
    )


def format_trial(report: TrialReport) -> str:
    groups = (
        ("fail_to_pass", report.classification.fail_to_pass),
        ("pass_to_pass", report.classification.pass_to_pass),
        ("still_failing", report.classification.still_failing),
        ("regression", report.classification.regression),
        ("skipped", report.classification.skipped),
    )
    total = sum(len(ids) for _name, ids in groups)
    absent = "SOLUTION_CHECK:absent" in report.trial_stdout.splitlines()
    lines = [
        f"repo {report.full_name}",
        f"commit {report.sha}",
        f"image {report.image}",
        f"memory {DEFAULT_MEMORY}",
        f"container_exit {report.container_exit}",
        f"before_pytest {report.before_status}",
        f"after_pytest {report.after_status}",
        f"solution_absent {'yes' if absent else 'no'}",
        "note A single run is not a validation gate.",
    ]
    for name, ids in groups:
        lines.append(f"{name} {len(ids)}")
        lines.extend(f"  {test_id}" for test_id in ids)
    lines.append(f"total {total}")
    lines.extend(
        [
            "--- before ---",
            report.before_stdout.rstrip("\n"),
            "--- before stderr ---",
            report.before_stderr.rstrip("\n"),
            "--- after ---",
            report.after_stdout.rstrip("\n"),
            "--- after stderr ---",
            report.after_stderr.rstrip("\n"),
        ]
    )
    return "\n".join(lines)


def _report(outcome: SandboxSuccess, *, image: str) -> TrialReport:
    if outcome.exit_code == 137:
        raise ForgeError(
            "Container was killed with exit 137 while the memory limit was "
            f"{DEFAULT_MEMORY}.\nstdout:\n{outcome.stdout}\nstderr:\n{outcome.stderr}",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    if "SOLUTION_CHECK:absent" not in outcome.stdout.splitlines():
        raise ForgeError(
            "The solution patch did not apply cleanly to the parent commit, "
            f"or the trial stopped early (container exit {outcome.exit_code}).\n"
            f"stdout:\n{outcome.stdout}\nstderr:\n{outcome.stderr}",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    before_stdout = _section(outcome.stdout, "---BEFORE-STDOUT---", "---BEFORE-STDERR---")
    before_stderr = _section(outcome.stdout, "---BEFORE-STDERR---", "---AFTER-STDOUT---")
    after_stdout = _section(outcome.stdout, "---AFTER-STDOUT---", "---AFTER-STDERR---")
    after_stderr = _section(outcome.stdout, "---AFTER-STDERR---", None)
    before = parse_pytest_verbose(before_stdout)
    after = parse_pytest_verbose(after_stdout)
    if not before or not after:
        raise ForgeError(
            "Pytest did not report a verbose result for both runs.\n"
            f"stdout:\n{outcome.stdout}\nstderr:\n{outcome.stderr}",
            reason=ReasonCode.SANDBOX_ERROR,
        )
    return TrialReport(
        full_name=outcome.full_name,
        sha=outcome.sha,
        image=image,
        container_exit=outcome.exit_code,
        before_status=_status(outcome.stdout, "BEFORE_STATUS"),
        after_status=_status(outcome.stdout, "AFTER_STATUS"),
        classification=classify(before, after),
        failed_before=tuple(
            sorted(test_id for test_id, status in before.items() if status == "fail")
        ),
        before_stdout=before_stdout,
        before_stderr=before_stderr,
        after_stdout=after_stdout,
        after_stderr=after_stderr,
        trial_stdout=outcome.stdout,
    )


def _section(text: str, start: str, end: str | None) -> str:
    lines = text.splitlines()
    try:
        begin = lines.index(start)
    except ValueError:
        raise ForgeError(
            f"Trial output is missing {start}.",
            reason=ReasonCode.SANDBOX_ERROR,
        ) from None
    if end is None:
        chunk = lines[begin + 1 :]
    else:
        try:
            stop = lines.index(end, begin + 1)
        except ValueError:
            raise ForgeError(
                f"Trial output is missing {end}.",
                reason=ReasonCode.SANDBOX_ERROR,
            ) from None
        chunk = lines[begin + 1 : stop]
    if not chunk:
        return ""
    return "\n".join(chunk) + "\n"


def _status(text: str, label: str) -> int:
    prefix = f"{label}:"
    for line in text.splitlines():
        if line.startswith(prefix) and line.removeprefix(prefix).isdigit():
            return int(line.removeprefix(prefix))
    raise ForgeError(
        f"Trial output is missing {label}.",
        reason=ReasonCode.SANDBOX_ERROR,
    )
