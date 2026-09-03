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

def test_the_real_roster_emits_exactly_the_devs_that_carry_a_handle():
    """A dev with `github: null` produces NOTHING and is recorded as a skip.

    Pieter Levels, Skirano and Sentient Agency are `github: null` in the committed YAML,
    so any assertion that the pool holds one entry per roster dev is asserting against
    data that does not exist.

    Derived from the file rather than pinned to a number, because the owner adding a dev
    is the documented way this list grows and it should not cost a test edit. What is
    pinned is the PROPERTY: emitted logins are exactly the non-null handles, and every
    dev without one is skipped with a reason.
    """
    raw = yaml.safe_load(Path(ROSTER).read_text(encoding="utf-8"))
    expected = sorted(d["github"].lower() for d in raw["devs"] if d.get("github"))
    unhandled = sorted(d["name"] for d in raw["devs"] if not d.get("github"))

    entries, skipped = roster_lane(ROSTER)
    assert sorted(c.login for c in entries) == expected
    assert sorted(s.name for s in skipped) == unhandled
    assert {s.reason for s in skipped} == {NO_HANDLE}


def test_every_roster_dev_is_either_emitted_or_skipped_and_none_is_silently_dropped():
    """THE COMPLETENESS PROPERTY, which is what the old count was really protecting.

    emitted + skipped == the devs in the file. A lane that quietly dropped somebody would
    satisfy any assertion about the entries it DID emit; only the arithmetic catches it.
    Stated as a property so that adding a dev — the one supported way this file changes —
    exercises the check instead of breaking it.
    """
    raw = yaml.safe_load(Path(ROSTER).read_text(encoding="utf-8"))
    entries, skipped = roster_lane(ROSTER)
    assert len(entries) + len(skipped) == len(raw["devs"])


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
    """One shared login COLLAPSES; every other roster dev stands alone.

    Counted off the lane's own output rather than a literal, so the owner adding a dev to
    the YAML exercises the merge instead of breaking this test. The property is the
    collapse: `simonw` appears in both lanes and must produce ONE candidate, not two.
    """
    entries, _ = roster_lane(ROSTER)
    vault = [Cand("simonw", ("note-1",), ("simonw/llm",), "vault", "")]
    merged = {c.login: c for c in assemble(vault, entries)}
    assert len(merged) == len(entries), (
        "simonw is in both lanes and collapses to one, so the merged count is exactly "
        "the roster count — every other roster dev standing alone")
    assert "simonw" in {c.login for c in entries}, "the premise: simonw IS on the roster"
    assert merged["simonw"].discovered_via == "vault"
    assert merged["simonw"].discovered_via_all == ("roster", "vault")
    assert merged["simonw"].name == "Simon Willison"
    assert merged["bcherny"].signal_hashes == (), "no vault provenance — a recorded fact"


# --- T08/T09: the budget and the ONE paid step ------------------------------

class _Cl:
    """A client whose get_user is the only paid call, with its own call counter so a
    test can assert the budget matches what actually left the process."""

    def __init__(self, users, fail=()):
        self.users = users
        self.fail = set(fail)
        self._calls = 0
        self._cache_hits = 0
        self.asked: list[str] = []

    def get_user(self, login):
        self._calls += 1
        self.asked.append(login)
        if login in self.fail:
            raise RuntimeError("boom")
        return self.users.get(login)


def _m(active_90d):
    from cerebro.gitintel.gharchive import WindowMetrics
    return {90: WindowMetrics(window_days=90, active_days=active_90d, pushes=active_90d)}


def _human(login):
    return {"login": login, "type": "User", "name": login.title(), "public_repos": 3}


def test_the_activity_floor_runs_before_the_paid_call_and_defers_it_entirely():
    """THE ARITHMETIC THE ORDERING EXISTS FOR: get_user on every contributor is ~6,000
    cold calls, 1.2 hours of the hourly budget, spent on people the FREE lane has already
    shown have no activity."""
    cands = [Cand("active", ("h",), (), "fanout", ""), Cand("quiet", ("h",), (), "fanout", "")]
    metrics = {"active": _m(40), "quiet": _m(1)}
    cl = _Cl({"active": _human("active"), "quiet": _human("quiet")})
    got = pool.paid_prefilter(cands, metrics, cl, cap=100)
    assert cl.asked == ["active"], "the below-floor candidate cost no REST call"
    assert got.calls_used == 1
    assert [c.login for c in got.kept] == ["active"]
    assert [(c.login, r) for c, r in got.deferred] == [("quiet", pool.PREFILTER_DEFERRED)]


def test_a_deferred_candidate_is_returned_not_dropped():
    """Suppression stays forbidden. Deferring an API call is not suppression, and the
    Court settled twice that a low activity count is an attribution fact about the feed,
    never a fact about a human."""
    cands = [Cand("quiet", ("h",), (), "fanout", "")]
    got = pool.paid_prefilter(cands, {"quiet": _m(0)}, _Cl({}), cap=100)
    assert got.kept == [] and got.rejected == []
    assert len(got.deferred) == 1
    assert got.deferred[0][0].signal_hashes == ("h",), "provenance survives the deferral"


def test_the_cap_is_hard_and_the_overflow_is_named_never_silent():
    cands = [Cand(f"u{i}", ("h",), (), "fanout", "") for i in range(5)]
    metrics = {f"u{i}": _m(40) for i in range(5)}
    cl = _Cl({f"u{i}": _human(f"u{i}") for i in range(5)})
    got = pool.paid_prefilter(cands, metrics, cl, cap=2)
    assert got.calls_used == 2 == cl._calls
    assert got.truncated is True
    truncated = [c.login for c, r in got.deferred if r == pool.PREFILTER_TRUNCATED]
    assert len(truncated) == 3
    assert len(got.kept) + len(got.deferred) == 5, "nobody vanishes at the cap"


def test_a_cap_of_zero_spends_nothing_and_defers_everybody():
    cands = [Cand("a", ("h",), (), "fanout", "")]
    cl = _Cl({"a": _human("a")})
    got = pool.paid_prefilter(cands, {"a": _m(40)}, cl, cap=0)
    assert cl._calls == 0 and got.calls_used == 0 and got.truncated is True


def test_a_non_human_is_rejected_by_the_e01_ruling_not_by_a_new_one():
    cands = [Cand("anorg", ("h",), (), "fanout", "")]
    cl = _Cl({"anorg": {"login": "anorg", "type": "Organization"}})
    got = pool.paid_prefilter(cands, {"anorg": _m(40)}, cl, cap=10)
    assert [c.login for c in got.rejected] == ["anorg"]
    assert got.kept == []


def test_a_raising_get_user_rejects_that_one_account_and_the_lane_continues():
    cands = [Cand("bad", ("h",), (), "fanout", ""), Cand("good", ("h",), (), "fanout", "")]
    metrics = {"bad": _m(40), "good": _m(40)}
    cl = _Cl({"good": _human("good")}, fail={"bad"})
    got = pool.paid_prefilter(cands, metrics, cl, cap=10)
    assert [c.login for c in got.kept] == ["good"]
    assert [c.login for c in got.rejected] == ["bad"]


def test_the_work_order_is_recurrence_first_and_orders_work_only():
    """F063. When the cap bites, the calls are spent on the repos the vault keeps coming
    back to, not on whichever login sorted first alphabetically."""
    cands = [Cand("zzz", ("h",), (), "fanout", ""), Cand("aaa", ("h",), (), "fanout", "")]
    metrics = {"zzz": _m(40), "aaa": _m(40)}
    cl = _Cl({"zzz": _human("zzz"), "aaa": _human("aaa")})
    got = pool.paid_prefilter(cands, metrics, cl, cap=1, order=["zzz", "aaa"])
    assert cl.asked == ["zzz"]
    assert got.truncated is True


def test_the_prefilter_floor_is_the_admission_constant_not_a_second_copy():
    """A private copy of the floor drifts from the real one the first time either moves,
    and the drift is silent."""
    from cerebro.gitintel.admission import MIN_ACTIVE_DAYS_90D
    cands = [Cand("edge", ("h",), (), "fanout", "")]
    cl = _Cl({"edge": _human("edge")})
    at = pool.paid_prefilter(cands, {"edge": _m(MIN_ACTIVE_DAYS_90D)}, cl, cap=10)
    assert [c.login for c in at.kept] == ["edge"]
    cl2 = _Cl({"edge": _human("edge")})
    below = pool.paid_prefilter(cands, {"edge": _m(MIN_ACTIVE_DAYS_90D - 1)}, cl2, cap=10)
    assert cl2._calls == 0 and len(below.deferred) == 1


def test_a_candidate_the_archive_never_returned_is_deferred_not_crashed():
    """78 of the real 175-owner pool has zero archive activity. A missing metrics entry
    is that case, never a KeyError."""
    got = pool.paid_prefilter([Cand("ghost", ("h",), (), "fanout", "")], {}, _Cl({}), cap=10)
    assert len(got.deferred) == 1


def test_the_budget_records_actual_against_cap_for_both_ceilings():
    b = pool.Budget(rest_calls_used=338, rest_calls_cap=1200, rest_cache_hits=7,
                    clickhouse_scans=3, fork_calls_used=12, fork_calls_cap=300)
    d = b.to_dict()
    assert d["rest_calls_used"] <= d["rest_calls_cap"]
    assert d["fork_calls_used"] <= d["fork_calls_cap"]
    assert d["clickhouse_scans"] == 3
    for key in ("rest_calls_used", "rest_cache_hits", "rest_calls_cap", "clickhouse_scans",
                "truncated", "skipped_logins", "fork_calls_used", "fork_calls_cap",
                "fork_budget_exhausted", "fork_unevidenced"):
        assert key in d, f"the artifact needs {key}"


def test_the_budget_carries_no_score_or_volume_field():
    d = pool.Budget().to_dict()
    flat = " ".join(d)
    for banned in ("score", "rank", "followers", "stars"):
        assert banned not in flat
