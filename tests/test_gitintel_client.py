from __future__ import annotations

from cerebro.gitintel.cache import GitIntelCache
from cerebro.gitintel.github_client import GitHubClient


class DummyResp:
    status_code = 200
    text = "{}"
    headers = {"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "59", "X-RateLimit-Reset": "1"}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class Settings:
    github = {"cache_path": ":memory:", "cache_ttl_hours": 24, "request_timeout_seconds": 3, "token_env": "NO_TOKEN"}


def test_github_client_uses_cache(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers, timeout))
        return DummyResp({"full_name": "filiksyos/gittoskill"})

    monkeypatch.setattr("requests.get", fake_get)
    client = GitHubClient(Settings())

    assert client.get_repo("filiksyos", "gittoskill")["full_name"] == "filiksyos/gittoskill"
    assert client.get_repo("filiksyos", "gittoskill")["full_name"] == "filiksyos/gittoskill"
    assert len(calls) == 1
    assert client.rate_limit["authenticated"] is False


def test_github_client_partitions_cache_by_token(monkeypatch):
    calls = []
    cache = GitIntelCache(":memory:")

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(headers["Authorization"])
        return DummyResp({"token": headers["Authorization"]})

    monkeypatch.setattr("requests.get", fake_get)

    first = GitHubClient(Settings(), token="token-a", cache=cache)
    second = GitHubClient(Settings(), token="token-b", cache=cache)

    assert first.get_repo("private", "repo")["token"] == "Bearer token-a"
    assert second.get_repo("private", "repo")["token"] == "Bearer token-b"
    assert calls == ["Bearer token-a", "Bearer token-b"]
