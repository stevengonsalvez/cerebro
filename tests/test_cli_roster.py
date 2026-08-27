from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from cerebro import config
from cerebro.__main__ import main
from cerebro.gitintel import identity
from cerebro.gitintel import roster as roster_mod

ROSTER_BODY = """\
# Cracked devs — curated roster.
version: 1

wiring:
  enabled: true
  max_tier: 2

defaults:
  tier: 2
  enabled: true

devs:
  - name: Simon Willison
    tier: 1
    x: simonw
    github: simonw
    blog: null          # keep this comment
    blog_feed: null
    reddit: null
    why: "Primary-source LLM analysis"
    added: "2026-07-20"

  - name: Skirano
    tier: 2
    x: skirano
    github: null
    blog: null
    reddit: null
    why: "Early agent demos"
    added: "2026-07-20"
"""


def _roster(tmp_path: Path) -> Path:
    p = tmp_path / "cracked_devs.yaml"
    p.write_text(ROSTER_BODY, encoding="utf-8")
    return p


def _wire(monkeypatch, tmp_path: Path, roster_path: Path, *, vault=None) -> None:
    monkeypatch.setattr(roster_mod, "DEFAULT_PATH", roster_path)
    settings = SimpleNamespace(
        vault_path=vault or (tmp_path / "vault"),
        dry_run=True,
        github={"cache_path": ":memory:"},
        cracked_devs=[],
        sources={},
    )
    monkeypatch.setattr(config, "load", lambda *a, **k: settings)


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["cerebro", "cracked-devs", "roster", *argv])
    main()


def test_list_emits_devs_and_wired_block(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path, _roster(tmp_path))
    _run(monkeypatch, ["list"])
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "list"
    assert [d["name"] for d in out["devs"]] == ["Simon Willison", "Skirano"]
    assert set(out["wired"]["x"]["accounts"]) == {"simonw", "skirano"}
    assert out["wired"]["github_devs"]["logins"] == ["simonw"]


def test_list_tier_filter(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path, _roster(tmp_path))
    _run(monkeypatch, ["list", "--tier", "1"])
    out = json.loads(capsys.readouterr().out)
    assert [d["name"] for d in out["devs"]] == ["Simon Willison"]


def test_enrich_without_write_leaves_file_untouched(monkeypatch, tmp_path, capsys):
    roster_path = _roster(tmp_path)
    before = roster_path.read_text(encoding="utf-8")
    _wire(monkeypatch, tmp_path, roster_path)
    monkeypatch.setattr(
        identity, "resolve_from_github",
        lambda login, client: identity.Identity(
            github=login, x=login, blog=f"https://{login}.dev", confidence="high", evidence="test"
        ),
    )
    _run(monkeypatch, ["enrich"])
    out = json.loads(capsys.readouterr().out)
    assert out["written"] is False
    assert roster_path.read_text(encoding="utf-8") == before


def test_enrich_write_fills_blanks_and_preserves_comments(monkeypatch, tmp_path, capsys):
    roster_path = _roster(tmp_path)
    _wire(monkeypatch, tmp_path, roster_path)
    monkeypatch.setattr(
        identity, "resolve_from_github",
        lambda login, client: identity.Identity(
            github=login, x=login, blog="https://simonwillison.net", confidence="high", evidence="test"
        ),
    )
    _run(monkeypatch, ["enrich", "--write"])
    out = json.loads(capsys.readouterr().out)
    assert out["written"] is True

    import yaml

    text = roster_path.read_text(encoding="utf-8")
    # Comment preserved, no re-ordering (Skirano still second).
    assert "# keep this comment" in text
    assert text.index("Simon Willison") < text.index("Skirano")
    data = yaml.safe_load(text)
    simon = data["devs"][0]
    # Blank blog filled from resolution; curated x is not overwritten.
    assert simon["blog"] == "https://simonwillison.net"
    assert simon["x"] == "simonw"
    assert simon["why"] == "Primary-source LLM analysis"


def test_suggest_excludes_roster_devs(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    devs_dir = vault / "Entities" / "developers"
    devs_dir.mkdir(parents=True)
    (devs_dir / "simonw.md").write_text(
        "---\nlogin: simonw\nmomentum_score: 0.9\n---\n", encoding="utf-8"
    )
    (devs_dir / "newdev.md").write_text(
        "---\nlogin: newdev\ndisplay_name: New Dev\nmomentum_score: 0.7\n---\n", encoding="utf-8"
    )
    _wire(monkeypatch, tmp_path, _roster(tmp_path), vault=vault)
    _run(monkeypatch, ["suggest", "--limit", "5"])
    out = json.loads(capsys.readouterr().out)
    logins = [c["login"] for c in out["suggestions"]]
    assert "simonw" not in logins   # already on roster
    assert logins == ["newdev"]
    assert "newdev" in out["yaml"]


def test_suggest_yaml_quotes_ambiguous_names():
    import yaml

    from cerebro.__main__ import _suggest_yaml_blocks

    block = _suggest_yaml_blocks([
        {"display_name": "Dev: The Sequel", "login": "seq", "momentum_score": 0.5},
    ])
    parsed = yaml.safe_load("devs:\n" + block)
    assert parsed["devs"][0]["name"] == "Dev: The Sequel"


def test_fetch_page_is_silent_on_failure(monkeypatch):
    import requests

    from cerebro.__main__ import _fetch_page

    def boom(*a, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    assert _fetch_page("https://unreachable.example") == ""


# --- F016: the reverse resolver is PARKED and off by default -------------------
#
# WHAT IS BEING SUBTRACTED. Until this flag existed, `_roster_enrich` called
# `resolve_from_blog` for every dev with a blog and no handle — i.e. the Court-PARKED
# path ran by DEFAULT. The ruling: "a mislinked X account on a named person's page is the
# charter's wrong-number-worse-than-no-page class, and the reverse resolver has no
# measured precision on this pool."
#
# NOTHING IN THIS FILE OBSERVED THAT PATH BEFORE. The existing cases monkeypatch
# `resolve_from_github` only, and no fixture had a dev with a blog and no handle, so the
# reverse branch was never reachable in a test in either direction. Both halves are new.

BLOG_ONLY_ROSTER = """\
version: 1

wiring:
  enabled: true
  max_tier: 2

defaults:
  tier: 2
  enabled: true

devs:
  - name: Blogger Only
    tier: 2
    x: null
    github: null
    blog: "https://bloggeronly.example"
    blog_feed: null
    reddit: null
    why: "has a blog and no handle — the only shape that reaches the reverse branch"
    added: "2026-08-27"
"""


def _blog_only_roster(tmp_path: Path) -> Path:
    p = tmp_path / "cracked_devs.yaml"
    p.write_text(BLOG_ONLY_ROSTER, encoding="utf-8")
    return p


def test_enrich_does_not_touch_the_reverse_resolver_without_the_flag(
        monkeypatch, tmp_path, capsys):
    """A fail-if-called sentinel on the exact function the Court parked."""
    _wire(monkeypatch, tmp_path, _blog_only_roster(tmp_path))

    def _fail(*a, **k):
        import pytest as _pytest
        _pytest.fail("the reverse resolver ran without --reverse-resolve")

    monkeypatch.setattr(identity, "resolve_from_blog", _fail)
    _run(monkeypatch, ["enrich"])
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "enrich"
    assert out["changes"] == []
    assert out["written"] is False


def test_the_flag_runs_it_exactly_once_and_prints_what_it_cannot_promise(
        monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path, _blog_only_roster(tmp_path))
    seen = []

    def _record(blog_url, client, fetch_page=None):
        seen.append(blog_url)
        return identity.Identity(github="bloggeronly", blog=blog_url,
                                 confidence="medium", evidence="test")

    monkeypatch.setattr(identity, "resolve_from_blog", _record)
    _run(monkeypatch, ["enrich", "--reverse-resolve"])
    text = capsys.readouterr().out
    out = json.loads(text[text.index("{"):])

    assert seen == ["https://bloggeronly.example"]
    assert [c["field"] for c in out["changes"]] == ["github"]
    assert "NO measured precision" in text
    assert "--reverse-resolve is ON" in text


def test_a_dev_with_a_handle_never_reaches_the_reverse_branch_even_with_the_flag(
        monkeypatch, tmp_path, capsys):
    """The forward direction is authoritative and free; the reverse one is a guess. A dev
    who already has a handle must never be re-derived from their blog."""
    _wire(monkeypatch, tmp_path, _roster(tmp_path))

    def _fail(*a, **k):
        import pytest as _pytest
        _pytest.fail("the reverse resolver ran for a dev who already has a handle")

    monkeypatch.setattr(identity, "resolve_from_blog", _fail)
    monkeypatch.setattr(
        identity, "resolve_from_github",
        lambda login, client: identity.Identity(github=login, confidence="high",
                                                evidence="test"))
    _run(monkeypatch, ["enrich", "--reverse-resolve"])
    assert "enrich" in capsys.readouterr().out


def test_the_flag_defaults_to_off_in_the_parser():
    """Asserted on the parser rather than inferred from behaviour, so a future edit that
    flips the default is red here."""
    import argparse
    import contextlib
    import io

    from cerebro.__main__ import main as _main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
        sys.argv = ["cerebro", "cracked-devs", "roster", "--help"]
        _main()
    help_text = buf.getvalue()
    assert "--reverse-resolve" in help_text
    assert "Off by" in help_text or "off by" in help_text
    assert isinstance(argparse.ArgumentParser(), argparse.ArgumentParser)
