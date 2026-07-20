from __future__ import annotations

from cerebro.gitintel.identity import (
    Identity,
    identity_links,
    merge_into,
    resolve_from_blog,
    resolve_from_github,
)
from cerebro.gitintel.roster import CrackedDev


class FakeClient:
    """No network. Returns whatever user/search payload it was constructed with."""

    def __init__(self, user=None, search=None):
        self._user = user
        self._search = search or {"items": []}

    def get_user(self, login):
        return self._user

    def search_users(self, q, limit=10):
        return self._search


def test_resolve_from_github_is_high_confidence():
    c = FakeClient(user={
        "login": "simonw", "html_url": "u", "blog": "simonwillison.net",
        "twitter_username": "simonw",
    })
    i = resolve_from_github("simonw", c)
    assert (i.github, i.x, i.blog, i.confidence) == (
        "simonw", "simonw", "https://simonwillison.net", "high",
    )


def test_resolve_from_github_missing_user_is_none():
    i = resolve_from_github("ghost", FakeClient(user=None))
    assert i.github == ""
    assert i.confidence == "none"


def test_resolve_from_blog_github_io():
    i = resolve_from_blog("https://bcherny.github.io/posts/1", FakeClient())
    assert i.github == "bcherny"
    assert i.confidence == "high"


def test_resolve_from_blog_html_link():
    html = (
        '<a href="https://github.com/features">f</a>'
        '<a href="https://github.com/realdev">me</a>'
    )
    i = resolve_from_blog("https://x.dev", FakeClient(), fetch_page=lambda u: html)
    assert i.github == "realdev"
    assert i.confidence == "medium"


def test_resolve_from_blog_search_single():
    i = resolve_from_blog("https://a.dev", FakeClient(search={"items": [{"login": "x"}]}))
    assert i.github == "x"
    assert i.confidence == "medium"


def test_resolve_from_blog_search_ambiguous():
    i = resolve_from_blog(
        "https://a.dev",
        FakeClient(search={"items": [{"login": "a"}, {"login": "b"}]}),
    )
    assert i.github == ""
    assert i.confidence == "low"


def test_merge_into_fills_empty_fields():
    dev = CrackedDev(name="A")
    _, changed = merge_into(dev, Identity(github="gh", x="tw"))
    assert dev.github == "gh"
    assert dev.x == "tw"
    assert set(changed) == {"github", "x"}


def test_merge_into_does_not_overwrite():
    dev = CrackedDev(name="A", github="existing")
    _, changed = merge_into(dev, Identity(github="new"))
    assert dev.github == "existing"
    assert changed == []


def test_identity_links_shape():
    links = identity_links(CrackedDev(name="A", blog="https://b"))
    assert links
    assert all("title" in l and "url" in l and "reason" in l for l in links)
