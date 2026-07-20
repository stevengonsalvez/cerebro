from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from cerebro import config
from cerebro.__main__ import main
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
    github: simonw
    why: "Primary-source LLM analysis"
    added: "2026-07-20"

  - name: New Cracked
    tier: 3
    github: newcracked
    why: "Auto-discovered"
    added: "2026-07-20"
    discovered_via: crackscan

  - name: Other Find
    tier: 3
    github: otherfind
    added: "2026-07-20"
    discovered_via: suggest
"""


def _roster(tmp_path: Path) -> Path:
    p = tmp_path / "cracked_devs.yaml"
    p.write_text(ROSTER_BODY, encoding="utf-8")
    return p


def _wire(monkeypatch, tmp_path: Path, roster_path: Path) -> None:
    monkeypatch.setattr(roster_mod, "DEFAULT_PATH", roster_path)
    settings = SimpleNamespace(
        vault_path=tmp_path / "vault",
        dry_run=True,
        github={"cache_path": ":memory:"},
        cracked_devs=[],
        sources={},
    )
    monkeypatch.setattr(config, "load", lambda *a, **k: settings)


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["cerebro", "cracked-devs", "roster", *argv])
    main()


def test_discovered_filter_returns_only_matching_source(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path, _roster(tmp_path))
    _run(monkeypatch, ["list", "--discovered", "crackscan"])
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "list"
    assert [d["name"] for d in out["devs"]] == ["New Cracked"]
    assert out["count"] == 1


def test_discovered_filter_no_matches_is_empty_json(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path, _roster(tmp_path))
    _run(monkeypatch, ["list", "--discovered", "nope"])
    out = json.loads(capsys.readouterr().out)
    assert out["devs"] == []
    assert out["count"] == 0
