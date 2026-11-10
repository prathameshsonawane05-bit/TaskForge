"""Quality checks V6, V7, and V8. Each one can fail on its own."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

FAIL_ASSERTION = "assertion"
FAIL_IMPORT = "import_or_attribute"
FAIL_OTHER = "other"

_IMPORT = re.compile(r"\b(?:ImportError|ModuleNotFoundError|AttributeError)\b")
_ASSERT = re.compile(r"\bAssertionError\b|(?:^|\s)assert\s")
_MISSING = re.compile(
    r"(?:has no attribute|cannot import name|No module named) ['\"]([^'\"]+)['\"]"
)
_MATCH = re.compile(r"""match\s*=\s*(?P<q>['"])(?P<msg>.*?)(?P=q)""")
_EXC_EQ = re.compile(
    r"""(?:str\(\s*[A-Za-z_][A-Za-z0-9_]*\s*\)|[A-Za-z_][A-Za-z0-9_]*\.value)"""
    r"""\s*==\s*(?P<q>['"])(?P<msg>.*?)(?P=q)"""
)


@dataclass(frozen=True)
class QualityReport:
    failures: tuple[tuple[str, str], ...]
    unfair: tuple[str, ...]
    leaked_line: str | None
    hidden: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.unfair and self.leaked_line is None and not self.hidden


def classify_failure(text: str) -> str:
    """Classify one before-run failure. Import and attribute errors win."""
    if _IMPORT.search(text):
        return FAIL_IMPORT
    if _ASSERT.search(text):
        return FAIL_ASSERTION
    return FAIL_OTHER


def failure_excerpt(before_stdout: str, test_id: str) -> str:
    lines = [line.strip() for line in before_stdout.splitlines() if test_id in line]
    if not lines:
        return before_stdout
    return "\n".join(lines)


def check_quality(
    *,
    before_stdout: str,
    fail_to_pass: Sequence[str],
    instruction: str,
    solution_patch: str,
    test_patch: str,
) -> QualityReport:
    failures: list[tuple[str, str]] = []
    unfair: list[str] = []
    for test_id in fail_to_pass:
        excerpt = failure_excerpt(before_stdout, test_id)
        kind = classify_failure(excerpt)
        failures.append((test_id, kind))
        if kind == FAIL_IMPORT and not _names_signature(instruction, excerpt):
            unfair.append(test_id)
    return QualityReport(
        failures=tuple(failures),
        unfair=tuple(unfair),
        leaked_line=leaked_line(solution_patch, instruction),
        hidden=tuple(hidden_messages(test_patch, instruction)),
    )


def added_source_lines(patch: str) -> tuple[str, ...]:
    """Added source lines, without diff headers or blank lines."""
    found: list[str] = []
    for line in patch.splitlines():
        if line.startswith(("+++", "---", "diff ", "@@", "index ", "new file", "deleted file")):
            continue
        if line.startswith("+"):
            body = line[1:].strip()
            if body:
                found.append(body)
    return tuple(found)


def leaked_line(solution_patch: str, instruction: str) -> str | None:
    """Return the instruction line that is an added source line, if any.

    A sentence that merely contains the source text is not that line.
    ``value() should return 1`` is not the code line ``return 1``.
    """
    added = set(added_source_lines(solution_patch))
    for raw in instruction.splitlines():
        if raw.strip() in added:
            return raw
    return None


def hidden_messages(test_patch: str, instruction: str) -> tuple[str, ...]:
    """Exact error strings in the test patch that the instruction omits."""
    missing: list[str] = []
    for message in exact_error_messages(test_patch):
        if message not in instruction:
            missing.append(message)
    return tuple(missing)


def exact_error_messages(test_patch: str) -> tuple[str, ...]:
    """Quoted pytest.raises match strings and exception-text equalities.

    ``assert value() == 1`` is a return-value check, not an error message.
    """
    found: list[str] = []
    for pattern in (_MATCH, _EXC_EQ):
        for match in pattern.finditer(test_patch):
            message = match.group("msg")
            if message and message not in found:
                found.append(message)
    return tuple(found)


def format_quality(report: QualityReport) -> str:
    lines: list[str] = []
    if report.unfair:
        lines.append("v6 unfair")
        for test_id in report.unfair:
            lines.append(f"  {test_id}")
    else:
        lines.append(f"v6 {_kind_header(report.failures)}")
    for test_id, kind in report.failures:
        lines.append(f"  {test_id} {kind}")
    if report.leaked_line is None:
        lines.append("v7 clean")
    else:
        lines.append("v7 leak")
        lines.append(f"matched {report.leaked_line}")
    if not report.hidden:
        lines.append("v8 clean")
    else:
        lines.append("v8 hidden_requirement")
        for message in report.hidden:
            lines.append(f"missing {message}")
    return "\n".join(lines)


def _kind_header(failures: tuple[tuple[str, str], ...]) -> str:
    """Name each distinct kind in the order it first appears.

    ``other`` is one kind. It is not a label for a mix of kinds.
    """
    kinds: list[str] = []
    for _test_id, kind in failures:
        if kind not in kinds:
            kinds.append(kind)
    if not kinds:
        return "none"
    return ", ".join(kinds)


def _names_signature(instruction: str, failure_text: str) -> bool:
    match = _MISSING.search(failure_text)
    if match is None:
        return False
    name = match.group(1).split(".")[-1]
    if name not in instruction:
        return False
    return re.search(rf"(?<![\w.]){re.escape(name)}\s*\(", instruction) is not None
