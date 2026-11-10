"""Guards that secrets and the spec path stay where git expects them."""

import json
import subprocess
from pathlib import Path

from forge.config import find_repo_root

_PACKAGE_FILES = (
    "instruction.md",
    "solution/solution.patch",
    "tests/test.patch",
    "tests/config.json",
    "task.json",
    "ATTRIBUTION.md",
)


def _tracked(root: Path) -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def test_env_file_is_not_tracked() -> None:
    root = find_repo_root()
    assert ".env" not in _tracked(root)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=root,
        check=False,
    )
    assert ignored.returncode == 0


def test_spec_path_is_lowercase_docs() -> None:
    root = find_repo_root()
    assert (root / "docs" / "SPEC.md").is_file()
    tracked = _tracked(root)
    assert "docs/SPEC.md" in tracked
    assert "docs/PROGRESS.md" in tracked
    assert not any(path.startswith("Docs/") for path in tracked)


def test_sample_is_tracked() -> None:
    root = find_repo_root()
    tracked = _tracked(root)
    sample = "output/sample/local-counter"
    names = (
        "task.json",
        "instruction.md",
        "solution/solution.patch",
        "tests/test.patch",
        "tests/config.json",
        "ATTRIBUTION.md",
    )
    for name in names:
        path = f"{sample}/{name}"
        assert path in tracked
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=root,
            check=False,
        )
        assert ignored.returncode != 0


def test_committed_packages_have_required_files() -> None:
    root = find_repo_root()
    tracked = _tracked(root)
    tasks = sorted(
        path for path in tracked if path.startswith("output/") and path.endswith("/task.json")
    )
    assert tasks
    for task in tasks:
        payload = json.loads((root / task).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        package = task.removesuffix("/task.json")
        for name in _PACKAGE_FILES:
            relative = f"{package}/{name}"
            assert relative in tracked
            assert (root / relative).is_file()


def test_ds_store_is_ignored() -> None:
    root = find_repo_root()
    assert ".DS_Store" not in _tracked(root)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".DS_Store"],
        cwd=root,
        check=False,
    )
    assert ignored.returncode == 0
