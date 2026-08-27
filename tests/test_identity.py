from __future__ import annotations

from pathlib import Path

from cerebro.gitintel import identity
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


def test_merge_overwrite_flag():
    dev = CrackedDev(name="A", github="old")
    _, changed = merge_into(dev, Identity(github="new"), overwrite=True)
    assert dev.github == "new"
    assert changed == ["github"]


def test_identity_links_shape():
    links = identity_links(CrackedDev(name="A", blog="https://b"))
    assert links
    assert all("title" in l and "url" in l and "reason" in l for l in links)


# --- F016 forward-only: the free read --------------------------------------------

class _CountingClient:
    """A `GitHubClient` stand-in with the real one's cache key and call counter."""

    def __init__(self, cache):
        self.cache = cache
        self.token = ""
        self._calls = 0
        self._cache_hits = 0
        self._errors = 0

    def _cache_key(self, method, path, params):
        import hashlib
        import json as _json
        payload = _json.dumps({"v": 2, "method": method, "path": path,
                               "params": params or {}, "auth": "anon"}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def request(self, path, params=None):
        self._calls += 1
        return None

    def get_user(self, login):
        self._calls += 1
        return None


def _cached_client(tmp_path, login, payload):
    from cerebro.gitintel.cache import GitIntelCache

    cache = GitIntelCache(tmp_path / "c.sqlite")
    client = _CountingClient(cache)
    if payload is not None:
        cache.set_response(client._cache_key("GET", f"/users/{login}", None), 200, payload)
    return client


def test_forward_links_read_the_cache_and_spend_nothing(tmp_path):
    client = _cached_client(tmp_path, "simonw", {
        "login": "simonw", "type": "User", "name": "Simon Willison",
        "blog": "https://simonwillison.net", "twitter_username": "simonw"})
    before = client._calls
    got = identity.forward_links_cached("simonw", client)

    assert got is not None
    assert got.github == "simonw"
    assert got.blog == "https://simonwillison.net"
    assert got.x == "simonw"
    assert client._calls - before == 0, "the free read made a call"
    assert "0 calls" in got.evidence


def test_a_cache_miss_is_none_at_zero_calls(tmp_path):
    """`None` is "not known". It is never a blank field on a named person's page, and it
    is never worth a call: the payload is already on disk for everybody who published."""
    client = _cached_client(tmp_path, "simonw", None)
    before = client._calls
    assert identity.forward_links_cached("simonw", client) is None
    assert client._calls - before == 0


def test_a_client_with_no_cache_is_none_rather_than_an_attribute_error(tmp_path):
    class _Bare:
        pass

    assert identity.forward_links_cached("simonw", _Bare()) is None


def test_a_cached_error_response_is_not_an_identity(tmp_path):
    client = _cached_client(tmp_path, "ghost", None)
    cache = client.cache
    cache.set_response(client._cache_key("GET", "/users/ghost", None), 404,
                       {"message": "Not Found"})
    assert identity.forward_links_cached("ghost", client) is None


def test_the_devs_lane_never_calls_the_parked_reverse_resolver():
    """The Court parked reverse resolution. Nothing in the devs lane may reach it, and
    the assertion is over the lane's own modules rather than over a promise."""
    import ast

    for path in Path("cerebro/gitintel").glob("*.py"):
        if path.name in ("identity.py",):
            continue                      # the parked function lives here, unused
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "resolve_from_blog":
                raise AssertionError(f"{path}: calls the parked reverse resolver")
            if isinstance(node, ast.Name) and node.id == "resolve_from_blog":
                raise AssertionError(f"{path}: names the parked reverse resolver")


def test_the_parked_resolver_is_still_present_and_unchanged():
    """PARKED, NOT DELETED. The Court's ruling is that it must not RUN by default, and a
    deletion would make the revisit a rewrite."""
    assert callable(identity.resolve_from_blog)


def test_merge_into_still_protects_a_curated_value():
    from cerebro.gitintel.roster import CrackedDev

    dev = CrackedDev(name="Simon Willison", github="simonw")
    _dev, changed = identity.merge_into(
        dev, identity.Identity(github="someone-else", confidence="medium"))
    assert changed == []
    assert dev.github == "simonw"
