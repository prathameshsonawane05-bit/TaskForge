"""Allowlist parsing."""

from pathlib import Path

import pytest

from forge.allowlist import load_allowlist
from forge.config import allowlist_path, find_repo_root
from forge.errors import ForgeError
from forge.models import ALLOWED_SPDX_IDS


def test_real_allowlist_names_the_chosen_repos() -> None:
    allow = load_allowlist(allowlist_path(find_repo_root()))
    assert allow.repos == (
        "pydantic/pydantic",
        "psf/requests",
        "pallets/click",
        "encode/httpx",
    )


def test_allowed_spdx_ids_are_only_the_permissive_set() -> None:
    assert ALLOWED_SPDX_IDS == frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"})


def test_membership_is_case_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.yaml"
    path.write_text("repos:\n  - Pydantic/Pydantic\n", encoding="utf-8")
    allow = load_allowlist(path)
    assert allow.contains("pydantic/pydantic")
    assert not allow.contains("torvalds/linux")


def test_malformed_allowlist_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.yaml"
    path.write_text("repos:\n  - not a repo\n", encoding="utf-8")
    with pytest.raises(ForgeError) as caught:
        load_allowlist(path)
    assert caught.value.reason == "config_error"
