"""Quality checks V6, V7, and V8. Each one can fail on its own."""

from __future__ import annotations

import ast
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
_OTHER_RESULT = re.compile(
    r"^(?:PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b.+\S::\S+"
    r"|^\S+::\S+\s+(?:PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b"
)
_BANNER = re.compile(r"^(?:=+|-+|_+)$")
_UNPARSED = "unparsed test"
_NONLITERAL = "nonliteral match"


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
    """The test-id line and the following lines through the end of that failure."""
    lines = before_stdout.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if test_id not in lines[index]:
            index += 1
            continue
        end = index + 1
        while end < len(lines) and not _next_failure(lines[end], test_id):
            end += 1
        blocks.append("\n".join(lines[index:end]))
        index = end
    if not blocks:
        return before_stdout
    return "\n".join(blocks)


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
    """Exact error strings in new test files that the instruction omits.

    ``nonliteral match`` and ``unparsed test`` are reasons. They stay hidden
    even when the instruction contains those words.
    """
    messages, reasons = _scan_tests(test_patch)
    missing = [message for message in messages if message not in instruction]
    for reason in reasons:
        if reason not in missing:
            missing.append(reason)
    return tuple(missing)


def exact_error_messages(test_patch: str) -> tuple[str, ...]:
    """String constants from pytest.raises matches and exception equalities.

    ``assert value() == 1`` is a return-value check, not an error message.
    A match that is not a constant, and a file that does not parse, are
    reported by :func:`hidden_messages` rather than as messages.
    """
    messages, _reasons = _scan_tests(test_patch)
    return messages


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
            if message in {_UNPARSED, _NONLITERAL}:
                lines.append(message)
            else:
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
    """True when the instruction text names the missing callable.

    This reads the instruction as text. It does not parse it as Python.
    ``myvalue(`` does not name ``value``. ``value(`` does.
    """
    match = _MISSING.search(failure_text)
    if match is None:
        return False
    name = match.group(1).split(".")[-1]
    if name not in instruction:
        return False
    return re.search(rf"(?<![\w.]){re.escape(name)}\s*\(", instruction) is not None


def _next_failure(line: str, test_id: str) -> bool:
    if test_id in line:
        return False
    stripped = line.strip()
    if _BANNER.match(stripped):
        return True
    return _OTHER_RESULT.match(stripped) is not None


def _scan_tests(test_patch: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    sources = _new_test_sources(test_patch)
    messages: list[str] = []
    reasons: list[str] = []
    for source in sources:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            if _UNPARSED not in reasons:
                reasons.append(_UNPARSED)
            continue
        visitor = _RaisedMessages()
        visitor.visit(tree)
        for message in visitor.messages:
            if message not in messages:
                messages.append(message)
        if visitor.nonliteral and _NONLITERAL not in reasons:
            reasons.append(_NONLITERAL)
    return tuple(messages), tuple(reasons)


def _new_test_sources(test_patch: str) -> list[str]:
    """Python text of each new file. A patch that is not a diff is one file."""
    if not test_patch.strip():
        return []
    if not _is_diff(test_patch):
        return [test_patch]
    sources: list[str] = []
    chunks = re.split(r"(?m)^(?=diff --git )", test_patch)
    for chunk in chunks:
        if "--- /dev/null" not in chunk and "new file mode" not in chunk:
            continue
        path = _added_path(chunk)
        if path is None or not path.endswith(".py"):
            continue
        sources.append(_added_source(chunk))
    return sources


def _is_diff(text: str) -> bool:
    return any(
        line.startswith("diff --git ") or line.startswith("--- /dev/null")
        for line in text.splitlines()
    )


def _added_path(chunk: str) -> str | None:
    for line in chunk.splitlines():
        if not line.startswith("+++ "):
            continue
        path = line[4:].strip()
        if path.startswith("b/"):
            path = path[2:]
        if path == "/dev/null":
            return None
        return path
    return None


def _added_source(chunk: str) -> str:
    lines: list[str] = []
    in_hunk = False
    for line in chunk.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("+"):
            lines.append(line[1:])
        elif line.startswith("\\"):
            continue
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _is_raises(func: ast.AST) -> bool:
    if isinstance(func, ast.Attribute) and func.attr == "raises":
        return True
    return isinstance(func, ast.Name) and func.id == "raises"


def _string_constant(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
        return node.value
    return None


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_exception_text(node: ast.AST) -> bool:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and not node.keywords
    ):
        return True
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "value"
        and isinstance(node.value, ast.Name)
    )


class _RaisedMessages(ast.NodeVisitor):
    """Collect constant error text. A non-constant match is only a flag."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.nonliteral = False

    def visit_Call(self, node: ast.Call) -> None:
        self._match(node)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._assert_test(node.test)
        self.generic_visit(node)

    def _match(self, node: ast.Call) -> None:
        if not _is_raises(node.func):
            return
        for keyword in node.keywords:
            if keyword.arg != "match":
                continue
            text = _string_constant(keyword.value)
            if text is not None:
                self._add(text)
            elif not _is_none(keyword.value):
                self.nonliteral = True

    def _assert_test(self, node: ast.expr) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Compare):
                self._compare(child)

    def _compare(self, compare: ast.Compare) -> None:
        nodes: list[ast.expr] = [compare.left, *compare.comparators]
        pairs = zip(compare.ops, nodes, nodes[1:], strict=False)
        for op, left, right in pairs:
            if not isinstance(op, ast.Eq):
                continue
            if _is_exception_text(left):
                text = _string_constant(right)
                if text is not None:
                    self._add(text)
            if _is_exception_text(right):
                text = _string_constant(left)
                if text is not None:
                    self._add(text)

    def _add(self, message: str) -> None:
        if message not in self.messages:
            self.messages.append(message)
