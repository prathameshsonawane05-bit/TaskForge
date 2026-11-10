"""A failed package write must leave the previous directory unchanged."""

from pathlib import Path

import pytest

from forge.errors import ForgeError
from forge.package import _write_patches, _write_pull_package
from forge.split import SplitReport

_SOLUTION = "diff --git a/pkg/widget.py b/pkg/widget.py\n"
_TEST = "diff --git a/tests/test_widget.py b/tests/test_widget.py\n"
_NEXT_SOLUTION = "diff --git a/pkg/next.py b/pkg/next.py\n"
_NEXT_TEST = "diff --git a/tests/test_next.py b/tests/test_next.py\n"


def _package(
    root: Path,
    *,
    instruction: str = "# Title\n\nTitle\n",
    source_patch: str = _SOLUTION,
    test_patch: str = _TEST,
) -> Path:
    return _write_pull_package(
        root=root,
        owner="acme",
        name="widgets",
        number=7,
        spdx="MIT",
        issue_url="https://github.com/acme/widgets/issues/12",
        base="a" * 40,
        merge="b" * 40,
        head="c" * 40,
        instruction=instruction,
        source_patch=source_patch,
        test_patch=test_patch,
        fail_to_pass=("tests/test_widget.py::test_one",),
        pass_to_pass=("tests/test_widget.py::test_keep",),
    )


def _split(source: str, test: str) -> SplitReport:
    return SplitReport(
        full_name="acme/widgets",
        number=7,
        source_files=("pkg/widget.py",),
        test_files=("tests/test_widget.py",),
        supporting_files=(),
        unsupported_files=(),
        source_patch=source,
        test_patch=test,
        issue_number=12,
        issue_url="https://github.com/acme/widgets/issues/12",
        issue_title="Handle empty input",
        issue_body="Fixes #12",
    )


def _marked_package(root: Path) -> Path:
    directory = root / "output" / "acme-widgets-7"
    directory.mkdir(parents=True)
    (directory / "MARKER").write_text("keep\n", encoding="utf-8")
    (directory / "solution").mkdir()
    (directory / "solution" / "solution.patch").write_text("old solution\n", encoding="utf-8")
    (directory / "tests").mkdir()
    (directory / "tests" / "test.patch").write_text("old test\n", encoding="utf-8")
    return directory


def _marked_patches(root: Path) -> Path:
    directory = root / "data" / "packages" / "acme" / "widgets" / "7" / "patches"
    directory.mkdir(parents=True)
    (directory / "MARKER").write_text("keep\n", encoding="utf-8")
    (directory / "solution.patch").write_text("old solution\n", encoding="utf-8")
    (directory / "test.patch").write_text("old test\n", encoding="utf-8")
    return directory


def _leftovers(directory: Path) -> list[str]:
    prefix = f".{directory.name}."
    return sorted(path.name for path in directory.parent.iterdir() if path.name.startswith(prefix))


def _assert_unchanged(directory: Path) -> None:
    assert (directory / "MARKER").read_text(encoding="utf-8") == "keep\n"
    if directory.name == "patches":
        assert (directory / "solution.patch").read_text(encoding="utf-8") == "old solution\n"
        assert (directory / "test.patch").read_text(encoding="utf-8") == "old test\n"
    else:
        solution = directory / "solution" / "solution.patch"
        test_patch = directory / "tests" / "test.patch"
        assert solution.read_text(encoding="utf-8") == "old solution\n"
        assert test_patch.read_text(encoding="utf-8") == "old test\n"
    assert not any("aside" in name for name in _leftovers(directory))


def test_empty_instruction_leaves_the_package(tmp_path: Path) -> None:
    directory = _marked_package(tmp_path)
    with pytest.raises(ForgeError, match="instruction.md is empty"):
        _package(tmp_path, instruction="\n")
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_empty_patch_leaves_the_package(tmp_path: Path) -> None:
    directory = _marked_package(tmp_path)
    with pytest.raises(ForgeError, match="solution.patch is empty"):
        _package(tmp_path, source_patch="")
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_patch_without_diff_header_leaves_the_package(tmp_path: Path) -> None:
    directory = _marked_package(tmp_path)
    with pytest.raises(ForgeError, match="no diff header"):
        _package(tmp_path, source_patch="@@ -1 +1 @@\n+new\n")
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_publish_rename_failure_restores_the_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _marked_package(tmp_path)
    real_rename = Path.rename

    def fake_rename(self: Path, target: Path) -> Path:
        if target == directory and ".aside" not in self.name:
            raise OSError("publish rename failed")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fake_rename)
    with pytest.raises(OSError, match="publish rename failed"):
        _package(tmp_path)
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_second_package_replaces_the_directory(tmp_path: Path) -> None:
    directory = _package(tmp_path)
    (directory / "MARKER").write_text("keep\n", encoding="utf-8")
    _package(tmp_path, instruction="# Next\n\nNext\n", source_patch=_NEXT_SOLUTION)
    assert not (directory / "MARKER").exists()
    text = (directory / "instruction.md").read_text(encoding="utf-8")
    assert "Next" in text
    solution = (directory / "solution" / "solution.patch").read_text(encoding="utf-8")
    assert solution == _NEXT_SOLUTION
    assert _leftovers(directory) == []


def test_second_patch_write_failure_leaves_the_old_test_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _marked_package(tmp_path)
    real_write = Path.write_text

    def fake_write(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        staged = any(part.startswith(".acme-widgets-7.") for part in self.parts)
        if self.name == "test.patch" and staged:
            raise OSError("second write failed")
        return real_write(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", fake_write)
    with pytest.raises(OSError, match="second write failed"):
        _package(tmp_path, source_patch=_NEXT_SOLUTION, test_patch=_NEXT_TEST)
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_missing_patch_file_leaves_the_patch_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _marked_patches(tmp_path)
    real_write = Path.write_text

    def fake_write(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        staged = any(part.startswith(".patches.") for part in self.parts)
        if self.name == "test.patch" and staged:
            return 0
        return real_write(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", fake_write)
    with pytest.raises(ForgeError, match="test.patch is missing"):
        _write_patches(tmp_path, "acme", "widgets", 7, _split(_SOLUTION, _TEST))
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_empty_patch_leaves_the_patch_directory(tmp_path: Path) -> None:
    directory = _marked_patches(tmp_path)
    with pytest.raises(ForgeError, match="test.patch is empty"):
        _write_patches(tmp_path, "acme", "widgets", 7, _split(_SOLUTION, ""))
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_patch_directory_rejects_a_missing_diff_header(tmp_path: Path) -> None:
    directory = _marked_patches(tmp_path)
    with pytest.raises(ForgeError, match="no diff header"):
        _write_patches(tmp_path, "acme", "widgets", 7, _split(_SOLUTION, "@@ -1 +1 @@\n+x\n"))
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_patch_directory_rename_failure_restores_the_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _marked_patches(tmp_path)
    real_rename = Path.rename

    def fake_rename(self: Path, target: Path) -> Path:
        if target == directory and ".aside" not in self.name:
            raise OSError("publish rename failed")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fake_rename)
    with pytest.raises(OSError, match="publish rename failed"):
        _write_patches(tmp_path, "acme", "widgets", 7, _split(_SOLUTION, _TEST))
    _assert_unchanged(directory)
    assert _leftovers(directory) == []


def test_second_patch_directory_replaces_and_leaves_no_aside(tmp_path: Path) -> None:
    directory = _write_patches(tmp_path, "acme", "widgets", 7, _split(_SOLUTION, _TEST))
    (directory / "MARKER").write_text("keep\n", encoding="utf-8")
    _write_patches(tmp_path, "acme", "widgets", 7, _split(_NEXT_SOLUTION, _NEXT_TEST))
    assert not (directory / "MARKER").exists()
    assert (directory / "solution.patch").read_text(encoding="utf-8") == _NEXT_SOLUTION
    assert (directory / "test.patch").read_text(encoding="utf-8") == _NEXT_TEST
    assert _leftovers(directory) == []
