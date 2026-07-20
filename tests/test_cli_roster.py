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
