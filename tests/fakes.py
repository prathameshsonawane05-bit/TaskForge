"""Shared fixtures for mocked GitHub responses."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from forge.github import GitHubClient, build_http_client

Handler = Callable[[httpx.Request], httpx.Response]


def repository_body(
    full_name: str,
    spdx_id: str | None,
    *,
    license_object: bool = True,
) -> str:
    if license_object:
        payload: dict[str, object] = {
            "full_name": full_name,
            "license": {"spdx_id": spdx_id, "name": spdx_id},
        }
    else:
        payload = {"full_name": full_name, "license": None}
    return json.dumps(payload)


def make_client(
    token: str,
    cache_path: Path,
    handler: Handler,
    sleeper: Callable[[float], None] | None = None,
    now: Callable[[], float] | None = None,
) -> GitHubClient:
    http = build_http_client(token, transport=httpx.MockTransport(handler))
    return GitHubClient(
        token=token,
        cache_path=cache_path,
        http_client=http,
        sleeper=sleeper,
        now=now,
    )


def write_project(root: Path, token_line: str, repos: list[str]) -> None:
    (root / "pyproject.toml").write_text("[project]\nname='mini'\n", encoding="utf-8")
    (root / ".env").write_text(token_line, encoding="utf-8")
    allow = root / "forge"
    allow.mkdir()
    lines = ["repos:", *[f"  - {repo}" for repo in repos], ""]
    (allow / "allowlist.yaml").write_text("\n".join(lines), encoding="utf-8")
