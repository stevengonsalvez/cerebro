from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cerebro.sources import github_devs


def _repo(name, *, days_ago=1, **kw):
    base = {
        "full_name": name,
        "name": name.split("/")[-1],
        "html_url": f"https://github.com/{name}",
        "pushed_at": (datetime.now(timezone.utc) - timedelta(days=days_ago))
        .isoformat().replace("+00:00", "Z"),
        "stargazers_count": 10,
        "fork": False,
        "archived": False,
        "description": "",
        "topics": [],
        "language": "",
    }
    base.update(kw)
    return base


def _patch(monkeypatch, repos):
    monkeypatch.setattr(github_devs.GitHubClient, "__init__", lambda self, s=None: None)
    monkeypatch.setattr(
        github_devs.GitHubClient, "get_user_repos", lambda self, login, limit=20: repos
    )


def test_empty_logins_short_circuits():
    assert github_devs.fetch({"logins": []}, SimpleNamespace()) == []


def test_basic_signal_from_repo(monkeypatch):
    _patch(monkeypatch, [_repo("simonw/datasette")])
    sigs = github_devs.fetch({"logins": ["simonw"]}, SimpleNamespace())
    assert len(sigs) == 1
    assert sigs[0].source == "github"
    assert "developer/simonw" in sigs[0].entity_tags
    assert "repo/simonw/datasette" in sigs[0].entity_tags


def test_forks_archived_and_stale_are_dropped(monkeypatch):
    _patch(monkeypatch, [
        _repo("a/fork", fork=True),
        _repo("a/arch", archived=True),
        _repo("a/stale", days_ago=90),
        _repo("a/good"),
    ])
    sigs = github_devs.fetch({"logins": ["a"], "window_days": 14}, SimpleNamespace())
    assert [s.meta["full_name"] for s in sigs] == ["a/good"]


def test_min_stars_filter(monkeypatch):
    _patch(monkeypatch, [
        _repo("a/small", stargazers_count=1),
        _repo("a/big", stargazers_count=99),
    ])
    sigs = github_devs.fetch({"logins": ["a"], "min_stars": 50}, SimpleNamespace())
    assert [s.meta["full_name"] for s in sigs] == ["a/big"]


def test_per_dev_cap(monkeypatch):
    _patch(monkeypatch, [_repo(f"a/r{i}") for i in range(10)])
    assert len(github_devs.fetch({"logins": ["a"], "per_dev": 3}, SimpleNamespace())) == 3


def test_client_error_on_one_dev_does_not_kill_source(monkeypatch):
    def boom(self, login, limit=20):
        if login == "bad":
            raise github_devs.GitHubClientError("429")
        return [_repo("ok/repo")]

    monkeypatch.setattr(github_devs.GitHubClient, "__init__", lambda self, s=None: None)
    monkeypatch.setattr(github_devs.GitHubClient, "get_user_repos", boom)
    sigs = github_devs.fetch({"logins": ["bad", "good"]}, SimpleNamespace())
    assert [s.meta["dev"] for s in sigs] == ["good"]
