"""Token loading reads .env and nothing else."""

from pathlib import Path

import pytest

from forge.config import default_cache_path, load_github_token
from forge.errors import MissingTokenError

ENV_TOKEN = "ghp_ENVIRONMENT_TOKEN_SHOULD_NOT_BE_USED"
DOTENV_TOKEN = "ghp_DOTENV_TOKEN_SHOULD_BE_USED"


def test_missing_env_file(tmp_path: Path) -> None:
    with pytest.raises(MissingTokenError) as caught:
        load_github_token(tmp_path / ".env")
    assert caught.value.reason == "missing_token"
    assert ENV_TOKEN not in str(caught.value)


def test_empty_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", ENV_TOKEN)
    (tmp_path / ".env").write_text("GITHUB_TOKEN=\n", encoding="utf-8")
    with pytest.raises(MissingTokenError) as caught:
        load_github_token(tmp_path / ".env")
    message = str(caught.value)
    assert "The GitHub call was not made." in message
    assert ENV_TOKEN not in message


def test_placeholder_token_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("GITHUB_TOKEN=your_token_here\n", encoding="utf-8")
    with pytest.raises(MissingTokenError):
        load_github_token(tmp_path / ".env")


def test_token_comes_from_dotenv_not_the_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", ENV_TOKEN)
    (tmp_path / ".env").write_text(f"GITHUB_TOKEN={DOTENV_TOKEN}\n", encoding="utf-8")
    loaded = load_github_token(tmp_path / ".env")
    assert loaded == DOTENV_TOKEN
    assert loaded != ENV_TOKEN


def test_quoted_token(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        'export GITHUB_TOKEN="ghp_QUOTED_TOKEN_VALUE_123456"\n',
        encoding="utf-8",
    )
    assert load_github_token(tmp_path / ".env") == "ghp_QUOTED_TOKEN_VALUE_123456"


def test_default_cache_path_is_under_data(tmp_path: Path) -> None:
    path = default_cache_path(tmp_path)
    assert path == tmp_path / "data" / "github_cache.sqlite"
    assert path.is_relative_to(tmp_path / "data")
