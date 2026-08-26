"""T05t/T06t — F008 roster lane and F015 slug-keyed dedup. No network.

Two failure modes are being made unrepresentable here.

DUPLICATE HUMANS. Six of the seven roster devs appear in the corpus, and the vault and
fan-out lanes both key on GitHub logins that differ only in case. Without dedup, day one
publishes two pages about one named person.

LANE-ORDER DEPENDENCE. `--lanes fanout,vault` is as legal an invocation as
`vault,fanout`. If the merge depended on the order, the same corpus would publish
different provenance on different days, and a transparency page that is quietly wrong
about a named human is worse than no page. The permutation test is the guard.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml

from cerebro.gitintel import pool
from cerebro.gitintel.pool import NO_HANDLE, Cand, assemble, roster_lane, slug

ROSTER = "config/cracked_devs.yaml"


# --- F015: the key -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("simonw", "simonw"), ("SimonW", "simonw"), ("@simonw", "simonw"),
    ("  @SimonW  ", "simonw"), ("", ""), (None, ""), ("   ", ""),
])
def test_the_identity_key_is_the_lowercased_at_stripped_login(raw, expected):
    assert slug(raw) == expected


def test_the_pool_does_not_import_the_roster_dataclass_to_key_itself():
    """The rule is restated for LOGINS rather than re-used from `CrackedDev.slug`. A pool
    that imported the roster type to key itself would break on the first login that never
    came from the roster — which is every lane but one."""
    import ast
    tree = ast.parse(Path("cerebro/gitintel/pool.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert "CrackedDev" not in imported
    # `slug()` is self-contained: it reads nothing but its own argument.
    assert slug("@SimonW") == "simonw"


# --- F015: the merge is order-independent -----------------------------------

def test_all_six_lane_orders_produce_a_byte_identical_result():
    """THE VALIDATION THE PLAN NAMES. One person found by three lanes, in all six
    orders, must collapse to one identical entry."""
    v = [Cand("simonw", ("aaa",), ("simonw/llm",), "vault", "")]
    f = [Cand("SimonW", (), ("datasette/datasette",), "fanout", "")]
    r = [Cand("simonw", (), (), "roster", "Simon Willison")]
    seen = set()
    for order in itertools.permutations([v, f, r]):
        out = assemble(*order)
        seen.add(tuple((c.login, c.discovered_via, c.discovered_via_all,
                        c.signal_hashes, c.via_repos, c.name) for c in out))
    assert len(seen) == 1, f"{len(seen)} distinct results across 6 lane orders"
    (only,) = seen
    assert len(only) == 1, "one person, one entry"
    login, via, via_all, hashes, repos, name = only[0]
    assert login == "simonw"
    assert via == "vault"
    assert via_all == ("fanout", "roster", "vault")
    assert hashes == ("aaa",)
    assert repos == ("datasette/datasette", "simonw/llm")
    assert name == "Simon Willison"


def test_signal_hashes_and_via_repos_are_unions_not_first_writer_wins():
    v = [Cand("x", ("h1", "h2"), ("a/b",), "vault", "")]
    f = [Cand("X", ("h2", "h3"), ("c/d",), "fanout", "")]
    (got,) = assemble(v, f)
    assert got.signal_hashes == ("h1", "h2", "h3")
    assert got.via_repos == ("a/b", "c/d")


def test_discovered_via_resolves_by_precedence_not_by_lane_order():
    """A person the vault cites DIRECTLY is vault-discovered even when fan-out also
    found them: the single string is the strongest claim the profile copy must stand
    behind."""
    v = [Cand("x", ("h",), (), "vault", "")]
    f = [Cand("x", (), (), "fanout", "")]
    r = [Cand("x", (), (), "roster", "X")]
    assert assemble(f, r, v)[0].discovered_via == "vault"
    assert assemble(f, r)[0].discovered_via == "roster"
    assert assemble(f)[0].discovered_via == "fanout"


def test_discovered_via_all_keeps_every_lane_so_the_precedence_stays_auditable():
    v = [Cand("x", ("h",), (), "vault", "")]
    f = [Cand("x", (), (), "fanout", "")]
    got = assemble(f, v)[0]
    assert got.discovered_via == "vault"
    assert got.discovered_via_all == ("fanout", "vault")


def test_the_curated_name_wins_and_is_where_the_frozen_name_field_stops_being_none():
    """No lane but the roster knows what a person is CALLED. The archive returns a login."""
    v = [Cand("simonw", ("h",), (), "vault", "")]
    r = [Cand("simonw", (), (), "roster", "Simon Willison")]
    assert assemble(v, r)[0].name == "Simon Willison"
    assert assemble(v)[0].name == ""


def test_the_surviving_login_casing_comes_from_the_precedent_lane():
    v = [Cand("simonw", ("h",), (), "vault", "")]
    f = [Cand("SIMONW", (), (), "fanout", "")]
    assert assemble(f, v)[0].login == "simonw"


def test_the_output_is_key_sorted_so_the_artifact_diffs_cleanly():
    lane = [Cand("zoe", (), (), "vault", ""), Cand("Alice", (), (), "vault", ""),
            Cand("bob", (), (), "vault", "")]
    assert [c.login for c in assemble(lane)] == ["Alice", "bob", "zoe"]


def test_a_blank_login_is_dropped_because_it_cannot_be_keyed():
    lane = [Cand("  ", (), (), "vault", ""), Cand("@", (), (), "vault", ""),
            Cand("real", (), (), "vault", "")]
    assert [c.login for c in assemble(lane)] == ["real"]


def test_assembling_nothing_is_an_empty_pool_not_a_crash():
    assert assemble() == []
    assert assemble([], [], []) == []


def test_an_unknown_lane_name_still_resolves_deterministically():
    """Falls back to a sorted scan, never to dict insertion order — which is exactly the
    lane-order dependence this module exists to remove."""
    a = [Cand("x", (), (), "zeta", "Z name")]
    b = [Cand("x", (), (), "alpha", "A name")]
    assert assemble(a, b)[0].discovered_via == assemble(b, a)[0].discovered_via == "alpha"
    assert assemble(a, b)[0].name == "A name"


# --- F008: the roster arithmetic, measured not assumed ----------------------

def test_the_real_roster_emits_four_entries_and_records_three_skips():
    """SEVEN devs, FOUR handles. Any assertion of seven pool entries is asserting
    against data that does not exist: Pieter Levels, Skirano and Sentient Agency are
    `github: null` in the committed YAML."""
    entries, skipped = roster_lane(ROSTER)
    assert sorted(c.login for c in entries) == ["bcherny", "mattpocock", "simonw", "t3dotgg"]
    assert sorted(s.name for s in skipped) == ["Pieter Levels", "Sentient Agency", "Skirano"]
    assert {s.reason for s in skipped} == {NO_HANDLE}


def test_the_file_really_does_carry_seven_devs_so_four_plus_three_is_the_whole_roster():
    """Pins the premise. If the owner adds a handle the counts move and this test tells
    you which way, instead of a lane silently emitting more entries."""
    raw = yaml.safe_load(Path(ROSTER).read_text(encoding="utf-8"))
    assert len(raw["devs"]) == 7
    entries, skipped = roster_lane(ROSTER)
    assert len(entries) + len(skipped) == 7


def test_no_handle_is_ever_invented_from_the_x_handle_or_the_display_name(tmp_path):
    """Guessing would attach a published profile to an account no human confirmed
    belongs to that person. `levelsio` is a real X handle AND a real GitHub login owned
    by somebody; deriving one from the other is the exact failure the verification
    doctrine calls worse than no page."""
    p = tmp_path / "roster.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "devs": [
        {"name": "Pieter Levels", "x": "levelsio", "github": None},
    ]}), encoding="utf-8")
    entries, skipped = roster_lane(p)
    assert entries == []
    assert [(s.name, s.reason) for s in skipped] == [("Pieter Levels", NO_HANDLE)]


def test_the_roster_lane_supplies_the_curated_name_and_no_signal_hashes(tmp_path):
    """Provenance comes from the dedup union, never invented by this lane. A roster dev
    the vault lane never produced therefore FAILS the provenance floor, which is recorded
    rather than excused."""
    entries, _ = roster_lane(ROSTER)
    by = {c.login: c for c in entries}
    assert by["simonw"].name == "Simon Willison"
    assert by["bcherny"].name == "Boris Cherny"
    assert all(c.signal_hashes == () for c in entries)
    assert all(c.via_repos == () for c in entries)
    assert all(c.discovered_via == "roster" for c in entries)


def test_adding_a_handle_to_the_yaml_emits_another_entry_with_zero_code_change(tmp_path):
    """The ONLY route by which the four moves. Populating the field is an owner decision
    on the file; the code never guesses."""
    p = tmp_path / "roster.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "devs": [
        {"name": "Pieter Levels", "x": "levelsio", "github": "levelsio"},
    ]}), encoding="utf-8")
    entries, skipped = roster_lane(p)
    assert [c.login for c in entries] == ["levelsio"]
    assert skipped == []


def test_a_missing_roster_file_is_an_empty_lane_not_a_crash(tmp_path):
    entries, skipped = roster_lane(tmp_path / "nope.yaml")
    assert entries == [] and skipped == []


def test_the_skip_is_a_record_not_a_log_line():
    """"Never suppressed" has to be auditable by reading an artifact, not by grepping
    stdout, so the skips are machine-readable data the census prints."""
    _entries, skipped = roster_lane(ROSTER)
    assert all(isinstance(s, pool.Skip) for s in skipped)
    assert all(s.name and s.reason for s in skipped)


def test_the_roster_lane_output_feeds_assemble_unchanged():
    entries, _ = roster_lane(ROSTER)
    vault = [Cand("simonw", ("note-1",), ("simonw/llm",), "vault", "")]
    merged = {c.login: c for c in assemble(vault, entries)}
    assert len(merged) == 4, "simonw collapses; the other three roster devs stand alone"
    assert merged["simonw"].discovered_via == "vault"
    assert merged["simonw"].discovered_via_all == ("roster", "vault")
    assert merged["simonw"].name == "Simon Willison"
    assert merged["bcherny"].signal_hashes == (), "no vault provenance — a recorded fact"
