"""License decisions. Allowlist membership alone does not accept a repository."""

from pathlib import Path

import httpx
import pytest

from forge.check import check_repository, decide_license, parse_full_name
from forge.errors import ForgeError
from forge.models import LicensePayload, ReasonCode, RepoPayload
from tests.fakes import make_client, repository_body, write_project

TOKEN = "ghp_FAKE_TOKEN_SHOULD_NOT_LEAK_12345"


@pytest.mark.parametrize(
    "spdx_id",
    ["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"],
)
def test_permissive_licenses_are_accepted(tmp_path: Path, spdx_id: str) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=repository_body("acme/widgets", spdx_id))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        result = check_repository("acme/widgets", root=tmp_path, client=client)
    assert calls == 1
    assert result.accepted is True
    assert result.spdx_id == spdx_id
    assert result.reason is None


@pytest.mark.parametrize(
    ("spdx_id", "reason"),
    [
        ("NOASSERTION", ReasonCode.LICENSE_NOASSERTION),
        ("BSD", ReasonCode.LICENSE_NOT_ALLOWED),
        ("BSD-4-Clause", ReasonCode.LICENSE_NOT_ALLOWED),
        ("0BSD", ReasonCode.LICENSE_NOT_ALLOWED),
        ("GPL-3.0", ReasonCode.LICENSE_NOT_ALLOWED),
        ("mit", ReasonCode.LICENSE_NOT_ALLOWED),
    ],
)
def test_other_spdx_ids_are_refused(spdx_id: str, reason: ReasonCode) -> None:
    repo = RepoPayload(full_name="acme/widgets", license=LicensePayload(spdx_id=spdx_id))
    result = decide_license("acme/widgets", repo)
    assert result.accepted is False
    assert result.reason == reason
    assert result.spdx_id == spdx_id


def test_null_license_is_refused() -> None:
    repo = RepoPayload.model_validate_json(
        repository_body("acme/widgets", None, license_object=False)
    )
    result = decide_license("acme/widgets", repo)
    assert result.accepted is False
    assert result.reason == ReasonCode.LICENSE_MISSING
    assert result.spdx_id is None


def test_allowlisted_repo_with_wrong_license_is_refused(tmp_path: Path) -> None:
    write_project(tmp_path, f"GITHUB_TOKEN={TOKEN}\n", ["acme/widgets"])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=repository_body("acme/widgets", "GPL-3.0"))

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        result = check_repository("Acme/Widgets", root=tmp_path, client=client)
    assert result.accepted is False
    assert result.reason == ReasonCode.LICENSE_NOT_ALLOWED
    assert result.spdx_id == "GPL-3.0"
    assert result.full_name == "acme/widgets"


def test_repo_not_on_the_allowlist_does_not_call_github(tmp_path: Path) -> None:
    write_project(tmp_path, "GITHUB_TOKEN=\n", ["acme/widgets"])

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("GitHub should not be called")

    with make_client(TOKEN, tmp_path / "cache.sqlite", handler) as client:
        result = check_repository("torvalds/linux", root=tmp_path, client=client)
    assert result.accepted is False
    assert result.reason == ReasonCode.NOT_ON_ALLOWLIST
    assert result.spdx_id is None


def test_invalid_repo_names() -> None:
    for value in ("linux", "owner/name/extra", "owner/..", "../name", "owner/name?x=1"):
        with pytest.raises(ForgeError) as caught:
            parse_full_name(value)
        assert caught.value.reason == ReasonCode.INVALID_REPO
