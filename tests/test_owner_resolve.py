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


# --- T04: the name/bio clause, demoted on measured evidence -------------------

def test_is_human_accepts_a_real_dev_with_no_name_and_no_bio():
    """Measured 2026-08-26 over the real 175-owner seed pool: a name/bio requirement
    dropped 8 of 91 human accounts, 7 of which ship high-star original work. An empty
    bio is a profile-completeness fact, not a humanness signal."""
    assert is_human({"type": "User", "login": "tt-a1i",
                     "public_repos": 61, "followers": 522}) is True
    assert is_human({"type": "User", "login": "BigPizzaV3",
                     "public_repos": 16, "followers": 419}) is True


def test_is_human_still_rejects_a_wholly_empty_shell():
    assert is_human({"type": "User", "login": "ghost",
                     "public_repos": 0, "followers": 0}) is False


def test_bot_and_vendor_rejection_survives_the_relaxation():
    assert is_human({"type": "User", "login": "renovate[bot]",
                     "public_repos": 900, "followers": 9000}) is False
    assert is_human({"type": "User", "login": "google",
                     "public_repos": 900, "followers": 9000}) is False
    assert is_human({"type": "Organization", "login": "n8n-io",
                     "public_repos": 900, "followers": 9000}) is False
