"""The built wheel carries the allowlist the loader reads from the repository."""

import subprocess
import sys
import zipfile
from pathlib import Path

from forge.config import find_repo_root


def test_wheel_contains_allowlist(tmp_path: Path) -> None:
    root = find_repo_root()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(tmp_path),
            str(root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
    assert "forge/allowlist.yaml" in names
