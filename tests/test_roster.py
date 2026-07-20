from __future__ import annotations

from cerebro.gitintel.roster import CrackedDev, active, apply_to_sources, load_roster


def _write(tmp_path, body):
    p = tmp_path / "cracked_devs.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_missing_file_returns_empty_and_disabled(tmp_path):
    devs, wiring = load_roster(tmp_path / "nope.yaml")
    assert devs == []
    assert wiring["enabled"] is False


def test_malformed_yaml_does_not_raise(tmp_path):
    p = _write(tmp_path, "devs: [ unclosed")
    devs, wiring = load_roster(p)
    assert devs == []
    assert wiring["enabled"] is False


def test_defaults_applied_and_handles_normalised(tmp_path):
    p = _write(tmp_path, """
version: 1
defaults:
  tier: 3
devs:
  - name: Test Dev
    x: "@handle"
    github: "  GhUser "
""")
    devs, _ = load_roster(p)
    assert devs[0].tier == 3
    assert devs[0].x == "handle"
    assert devs[0].github == "GhUser"
    assert devs[0].slug == "ghuser"


def test_entry_without_name_is_skipped(tmp_path):
    p = _write(tmp_path, "devs:\n  - x: ghost\n  - name: Real\n")
    devs, _ = load_roster(p)
    assert [d.name for d in devs] == ["Real"]


def test_max_tier_filters(tmp_path):
    p = _write(tmp_path, """
wiring: {max_tier: 1}
devs:
  - {name: A, tier: 1, x: a}
  - {name: B, tier: 2, x: b}
""")
    devs, wiring = load_roster(p)
    assert [d.name for d in active(devs, wiring)] == ["A"]


def test_apply_to_sources_merges_and_dedups_case_insensitively():
    devs = [
        CrackedDev(name="A", x="Alpha", blog_feed="https://a.dev/feed"),
        CrackedDev(name="B", x="beta", github="bee", reddit="bruser"),
    ]
    sources = {"x": {"accounts": ["alpha"]}, "rss": {"feeds": ["https://a.dev/feed"]}}
    out = apply_to_sources(sources, devs, {"enabled": True})
    assert out["x"]["accounts"] == ["alpha", "beta"]          # Alpha deduped, original casing kept
    assert out["rss"]["feeds"] == ["https://a.dev/feed"]      # exact dup dropped
    assert out["github_devs"]["logins"] == ["bee"]
    assert out["reddit_users"]["users"] == ["bruser"]


def test_wiring_disabled_is_a_noop():
    sources = {"x": {"accounts": ["only"]}}
    out = apply_to_sources(sources, [CrackedDev(name="A", x="new")], {"enabled": False})
    assert out["x"]["accounts"] == ["only"]


def test_selective_wiring_flags():
    devs = [CrackedDev(name="A", x="a", blog_feed="https://a/feed")]
    out = apply_to_sources({}, devs, {"enabled": True, "feed_x": True, "feed_rss": False})
    assert out["x"]["accounts"] == ["a"]
    assert out.get("rss", {}).get("feeds", []) == []
