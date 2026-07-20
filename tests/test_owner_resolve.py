from __future__ import annotations

from cerebro.gitintel.owner_resolve import is_human, resolve_owner


class FakeClient:
    """No network. Serves user payloads by login and contributor lists by repo."""

    def __init__(self, users=None, contributors=None):
        self._users = users or {}
        self._contributors = contributors or {}

    def get_user(self, login):
        return self._users.get(login)

    def request(self, path, params=None):
        # path like /repos/owner/name/contributors
        full = path[len("/repos/"):-len("/contributors")]
        return self._contributors.get(full, [])


def test_is_human_accepts_real_user():
    assert is_human({"type": "User", "login": "simonw", "name": "Simon"}) is True
    assert is_human({"type": "User", "login": "dev", "bio": "builds things"}) is True


def test_is_human_rejects_organization():
    assert is_human({"type": "Organization", "login": "acme", "name": "Acme"}) is False


def test_is_human_rejects_bot():
    assert is_human({"type": "User", "login": "dependabot[bot]", "name": "Bot"}) is False


def test_is_human_rejects_vendor_org():
    assert is_human({"type": "User", "login": "vercel", "name": "Vercel"}) is False


def test_is_human_rejects_empty():
    assert is_human({"type": "User", "login": "ghost"}) is False


def test_resolve_owner_human_owner():
    c = FakeClient(users={"simonw": {"type": "User", "login": "simonw", "name": "Simon"}})
    assert resolve_owner("simonw/datasette", c) == "simonw"


def test_resolve_owner_org_falls_to_top_human_committer():
    c = FakeClient(
        users={
            "acme": {"type": "Organization", "login": "acme"},
            "bot[bot]": {"type": "User", "login": "bot[bot]"},
            "realdev": {"type": "User", "login": "realdev", "name": "Real Dev"},
        },
        contributors={"acme/tool": [{"login": "bot[bot]"}, {"login": "realdev"}]},
    )
    assert resolve_owner("acme/tool", c) == "realdev"


def test_resolve_owner_org_no_human_returns_none():
    c = FakeClient(
        users={
            "acme": {"type": "Organization", "login": "acme"},
            "ghost": {"type": "User", "login": "ghost"},
        },
        contributors={"acme/tool": [{"login": "ghost"}]},
    )
    assert resolve_owner("acme/tool", c) is None
