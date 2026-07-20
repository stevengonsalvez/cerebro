from __future__ import annotations

from types import SimpleNamespace

from cerebro.sources import reddit_users


class DummyResp:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content


def _rss(title="Hello", link="https://reddit.com/x"):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        f"<entry><title>{title}</title>"
        f'<link href="{link}"/>'
        "<published>2026-07-20T00:00:00+00:00</published>"
        "</entry></feed>"
    ).encode("utf-8")


def _patch(monkeypatch, resp_for_url):
    calls = []

    def fake_get(url, limit):
        calls.append((url, limit))
        return resp_for_url(url)

    monkeypatch.setattr(reddit_users, "_get", fake_get)
    monkeypatch.setattr(reddit_users.time, "sleep", lambda *_a, **_k: None)
    return calls


def test_empty_users_short_circuits_without_http(monkeypatch):
    calls = _patch(monkeypatch, lambda url: DummyResp(200, _rss()))
    sigs = reddit_users.fetch({"users": []}, SimpleNamespace())
    assert sigs == []
    assert calls == []


def test_handles_are_normalised_and_not_mangled(monkeypatch):
    calls = _patch(monkeypatch, lambda url: DummyResp(200, _rss()))
    reddit_users.fetch({"users": ["u/name", "@name", "uuu_dev"]}, SimpleNamespace())
    users_hit = [url.split("/user/")[1].split("/submitted")[0] for url, _ in calls]
    assert users_hit == ["name", "name", "uuu_dev"]


def test_clean_prefix_check():
    assert reddit_users._clean("u/name") == "name"
    assert reddit_users._clean("@name") == "name"
    assert reddit_users._clean("uuu_dev") == "uuu_dev"
    assert reddit_users._clean("user123") == "user123"


def test_non_200_status_skipped_silently(monkeypatch):
    _patch(monkeypatch, lambda url: DummyResp(404, b""))
    sigs = reddit_users.fetch({"users": ["ghost"]}, SimpleNamespace())
    assert sigs == []


def test_signals_carry_dev_tags(monkeypatch):
    _patch(monkeypatch, lambda url: DummyResp(200, _rss("Post", "https://reddit.com/p1")))
    sigs = reddit_users.fetch({"users": ["simonw"]}, SimpleNamespace())
    assert len(sigs) == 1
    s = sigs[0]
    assert s.source == "reddit"
    assert s.title == "Post"
    assert "reddit/cracked-dev" in s.source_tags
    assert "developer/simonw" in s.entity_tags
    assert s.meta["dev"] == "simonw"
