from __future__ import annotations

from cerebro.gitintel.github_client import resolve_token


class Settings:
    github = {"token_env": "GITHUB_TOKEN"}


def test_cfg_token_env_wins_when_set(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN_CRACKSCAN", "cracked-value")
    assert resolve_token({"token_env": "GITHUB_TOKEN_CRACKSCAN"}, Settings()) == "cracked-value"


def test_unset_crackscan_env_returns_none(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN_CRACKSCAN", raising=False)
    assert resolve_token({"token_env": "GITHUB_TOKEN_CRACKSCAN"}, Settings()) is None


def test_falls_back_to_settings_then_github_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("SETTINGS_ENV", "from-settings")

    class S:
        github = {"token_env": "SETTINGS_ENV"}

    # no token_env in cfg -> settings.github.token_env
    assert resolve_token({}, S()) == "from-settings"
    assert resolve_token(None, S()) == "from-settings"

    # no cfg, no settings -> GITHUB_TOKEN
    monkeypatch.setenv("GITHUB_TOKEN", "default-token")
    assert resolve_token(None, None) == "default-token"
