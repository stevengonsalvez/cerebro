from __future__ import annotations

import types

from cerebro.gitintel import roster as roster_mod
from cerebro.gitintel.cache import GitIntelCache
from cerebro.sources import crackscan

NOW = "2026-06-30T00:00:00+00:00"
WEEK_AGO = "2026-06-23T00:00:00+00:00"


def _human(login, name="Real Dev"):
    return {
        "login": login,
        "type": "User",
        "name": name,
        "html_url": f"https://github.com/{login}",
        "followers": 300,
        "public_repos": 40,
        "created_at": "2025-01-01T00:00:00Z",
    }


def _repos(login):
    return [
        {"full_name": f"{login}/hot", "html_url": "u", "pushed_at": NOW},
        {"full_name": f"{login}/warm", "html_url": "u", "pushed_at": WEEK_AGO},
    ]


def _push(created_at, size=5):
    return {"type": "PushEvent", "created_at": created_at, "payload": {"size": size}}


class FakeClient:
    """No network. Serves users by login, contributors by repo, events by login."""

    def __init__(self, *, users=None, repos=None, contributors=None, events=None,
                 remaining=None):
        self.users = users or {}
        self.repos = repos or {}
        self.contributors = contributors or {}
        self.events = events or {}
        self.cache = GitIntelCache(":memory:")
        self.rate_limit = {"remaining": remaining} if remaining is not None else {}

    def get_user(self, login):
        return self.users.get(login)

    def get_user_repos(self, login, limit=20):
        return self.repos.get(login, [])

    def request(self, path, params=None):
        if path.endswith("/contributors"):
            full = path[len("/repos/"):-len("/contributors")]
            return self.contributors.get(full, [])
        if path.endswith("/events"):
            login = path.split("/")[2]
            return self.events.get(login, [])
        return None


def _settings():
    return types.SimpleNamespace(vault_path="", github={})


def _write_roster(tmp_path, *, extra_dev=""):
    text = (
        "# curated roster — keep these comments\n"
        "version: 1\n"
        "\n"
        "wiring:\n"
        "  enabled: true\n"
        "\n"
        "devs:\n"
        "  - name: Seed One\n"
        "    tier: 1\n"
        "    github: seedone\n"
        "    discovered_via: seed  # do not lose this\n"
        f"{extra_dev}"
    )
    p = tmp_path / "cracked_devs.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _fetch(monkeypatch, fake, cfg, settings=None):
    monkeypatch.setattr(crackscan, "GitHubClient",
                        lambda settings=None, token=None: fake)
    return crackscan.fetch(cfg, settings or _settings())


def test_empty_seeds_no_admits(monkeypatch, tmp_path):
    p = _write_roster(tmp_path)
    before = p.read_text(encoding="utf-8")
    out = _fetch(monkeypatch, FakeClient(), {"seed_repos": [], "roster_path": str(p)})
    assert out == []
    assert p.read_text(encoding="utf-8") == before  # untouched


def test_org_repo_admits_human_committer(monkeypatch, tmp_path):
    p = _write_roster(tmp_path)
    fake = FakeClient(
        users={
            "acme": {"login": "acme", "type": "Organization"},
            "realdev": _human("realdev", "Real Dev"),
        },
        repos={"realdev": _repos("realdev")},
        contributors={"acme/tool": [{"login": "realdev"}]},
        events={"realdev": [_push("2026-06-%02dT00:00:00Z" % d, size=8) for d in range(1, 21)]},
    )
    out = _fetch(monkeypatch, fake, {
        "seed_repos": ["acme/tool"], "roster_path": str(p),
        "score_threshold": 0.02, "now": NOW,
    })
    admitted = [s for s in out if "crackscan/admitted" in s.source_tags]
    assert [s.meta["login"] for s in admitted] == ["realdev"]  # human, not the org
    text = p.read_text(encoding="utf-8")
    assert "github: realdev" in text
    assert "discovered_via: crackscan" in text
    assert "acme" not in text


def test_dedup_existing_roster(monkeypatch, tmp_path):
    extra = (
        "  - name: Builder\n"
        "    tier: 2\n"
        "    github: builder\n"
        "    discovered_via: seed\n"
    )
    p = _write_roster(tmp_path, extra_dev=extra)
    before = p.read_text(encoding="utf-8")
    fake = FakeClient(
        users={"builder": _human("builder", "Builder")},
        repos={"builder": _repos("builder")},
    )
    out = _fetch(monkeypatch, fake, {
        "seed_repos": ["builder/hot"], "roster_path": str(p),
        "score_threshold": 0.02, "now": NOW,
    })
    assert [s for s in out if "crackscan/admitted" in s.source_tags] == []
    assert p.read_text(encoding="utf-8") == before  # already known → no write


def test_below_threshold_considered_only(monkeypatch, tmp_path):
    p = _write_roster(tmp_path)
    before = p.read_text(encoding="utf-8")
    fake = FakeClient(
        users={"realdev": _human("realdev")},
        repos={"realdev": _repos("realdev")},
    )
    out = _fetch(monkeypatch, fake, {
        "seed_repos": ["realdev/hot"], "roster_path": str(p),
        "score_threshold": 0.99, "now": NOW,
    })
    assert [s for s in out if "crackscan/admitted" in s.source_tags] == []
    considered = [s for s in out if "crackscan/considered" in s.source_tags]
    assert [s.meta["login"] for s in considered] == ["realdev"]
    assert p.read_text(encoding="utf-8") == before


def test_admit_max_caps_writes(monkeypatch, tmp_path):
    p = _write_roster(tmp_path)
    fake = FakeClient(
        users={"u1": _human("u1"), "u2": _human("u2")},
        repos={"u1": _repos("u1"), "u2": _repos("u2")},
    )
    out = _fetch(monkeypatch, fake, {
        "seed_repos": ["u1/a", "u2/b"], "roster_path": str(p),
        "score_threshold": 0.02, "admit_max": 1, "now": NOW,
    })
    admitted = [s for s in out if "crackscan/admitted" in s.source_tags]
    considered = [s for s in out if "crackscan/considered" in s.source_tags]
    assert len(admitted) == 1        # cap respected
    assert len(considered) == 1      # the extra is logged, not written
    devs, _ = roster_mod.load_roster(p)
    assert sum(1 for d in devs if d.discovered_via == "crackscan") == 1


def test_budget_guard_skips_deep_still_admits(monkeypatch, tmp_path):
    p = _write_roster(tmp_path)
    fake = FakeClient(
        users={"realdev": _human("realdev")},
        repos={"realdev": _repos("realdev")},
        # heavy events would boost the score, but the deep pass must be skipped
        events={"realdev": [_push("2026-06-%02dT00:00:00Z" % d, size=20) for d in range(1, 29)]},
        remaining="10",
    )
    out = _fetch(monkeypatch, fake, {
        "seed_repos": ["realdev/hot"], "roster_path": str(p),
        "score_threshold": 0.02, "min_remaining": 200, "now": NOW,
    })
    admitted = [s for s in out if "crackscan/admitted" in s.source_tags]
    assert len(admitted) == 1
    assert admitted[0].meta["deep"] is False          # deep pass skipped
    assert admitted[0].meta["commits_per_day"] == 0.0


def test_append_devs_preserves_comments_and_order(tmp_path):
    p = _write_roster(tmp_path)
    added = roster_mod.append_devs(str(p), [
        {"name": "New Dev", "github": "newdev", "discovered_via": "crackscan"},
    ])
    assert added == ["newdev"]
    text = p.read_text(encoding="utf-8")
    assert "# curated roster — keep these comments" in text
    assert "discovered_via: seed  # do not lose this" in text   # comment survives
    assert text.index("github: seedone") < text.index("github: newdev")  # order kept
    assert "discovered_via: crackscan" in text
    # idempotent: re-appending the same slug is a no-op
    assert roster_mod.append_devs(str(p), [{"name": "New Dev", "github": "newdev"}]) == []


def test_unset_token_falls_back(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_TOKEN_CRACKSCAN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    p = _write_roster(tmp_path)
    # resolve_token returns None → GitHubClient(...) falls back to its own env read; no crash
    out = _fetch(monkeypatch, FakeClient(), {"seed_repos": [], "roster_path": str(p)})
    assert out == []


# --- T03t: F001 vault Signal-note seed lane, behind a default-off flag ---------

def _seeded_vault(tmp_path):
    """A vault whose Signals corpus references real-looking github repos."""
    d = tmp_path / "vault" / "Signals"
    d.mkdir(parents=True)
    for i, full in enumerate(("alpha/one", "beta/two", "gamma/three")):
        (d / f"note{i}.md").write_text(
            f"---\nurl: https://github.com/{full}\ncaptured: 2026-01-0{i + 1}T00:00:00+00:00\n---\nbody\n",
            encoding="utf-8",
        )
    return str(tmp_path / "vault")


class CountingClient(FakeClient):
    """Records every call so 'zero client calls' can be asserted, not assumed."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = 0

    def get_user(self, login):
        self.calls += 1
        return super().get_user(login)

    def get_user_repos(self, login, limit=20):
        self.calls += 1
        return super().get_user_repos(login, limit=limit)

    def request(self, path, params=None):
        self.calls += 1
        return super().request(path, params)


def test_seed_lane_on_contributes_vault_signal_repos(tmp_path):
    settings = types.SimpleNamespace(vault_path=_seeded_vault(tmp_path), github={})
    seeds = crackscan._seed_repos({"use_vault_seed_lane": True}, settings)
    assert set(seeds) == {"alpha/one", "beta/two", "gamma/three"}


def test_seed_lane_on_with_absent_vault_path_contributes_nothing(tmp_path):
    settings = types.SimpleNamespace(vault_path="", github={})
    assert crackscan._seed_repos({"use_vault_seed_lane": True}, settings) == []
    settings = types.SimpleNamespace(vault_path=str(tmp_path / "nope"), github={})
    assert crackscan._seed_repos({"use_vault_seed_lane": True}, settings) == []


def test_seed_lane_defaults_off_over_a_populated_signals_corpus(tmp_path):
    """Default-off is ASSERTED, not assumed: the same vault yields nothing without the flag."""
    settings = types.SimpleNamespace(vault_path=_seeded_vault(tmp_path), github={})
    assert crackscan._seed_repos({}, settings) == []
    assert crackscan._seed_repos({"seed_repos": ["x/y"]}, settings) == ["x/y"]
    assert crackscan._seed_repos({"use_vault_seed_lane": False}, settings) == []


def test_shipped_config_defaults_the_lane_off():
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))
    assert cfg["crackscan"]["use_vault_seed_lane"] is False


def test_fetch_over_a_seeded_vault_with_the_flag_off_emits_zero_signals(monkeypatch, tmp_path):
    """The considered-Signal leak is not widened by e01.

    crackscan is enabled: true in production and fetch() still emits a
    `crackscan/considered` Signal per non-admitted candidate. The ONLY thing keeping
    that funnel inert is _seed_repos() returning []. This test fails loudly if a later
    commit flips the default.
    """
    p = _write_roster(tmp_path)
    before = p.read_text(encoding="utf-8")
    settings = types.SimpleNamespace(vault_path=_seeded_vault(tmp_path), github={})
    fake = CountingClient(users={"alpha": _human("alpha")})
    monkeypatch.setattr(crackscan, "GitHubClient", lambda settings=None, token=None: fake)
    called = []
    monkeypatch.setattr(roster_mod, "append_devs",
                        lambda *a, **k: called.append(a) or [])

    out = crackscan.fetch({"roster_path": str(p)}, settings)

    assert out == []                                    # zero Signals of either tag
    assert fake.calls == 0                              # zero GitHub client calls
    assert called == []                                 # no roster write
    assert p.read_text(encoding="utf-8") == before
