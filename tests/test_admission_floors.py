"""T10t/T11t — F025/F026/F018/F029/F068 admission floors and consistency ordering."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from cerebro.gitintel import admission
from cerebro.gitintel.admission import Candidate, admit, order_by_consistency
from cerebro.gitintel.gharchive import _parse_tsv

FIXTURE = Path(__file__).parent / "fixtures" / "gharchive_cohort_90d.tsv"
COHORT = _parse_tsv(FIXTURE.read_text(encoding="utf-8"), 90)


def cand(login="dev", *, hashes=("abc123",), days90=60, days30=20, automation="clear"):
    return Candidate(login=login, signal_hashes=tuple(hashes), active_days_90d=days90,
                     active_days_30d=days30, automation=automation)


# --- F068: the 0.02-override defect class is UNREPRESENTABLE ------------------

def test_admit_takes_exactly_one_parameter():
    """The scorer this replaces shipped broken for six production runs because all four
    of its admission tests overrode the real 0.55 threshold with 0.02. Not one exercised
    the value that ran. There is no seam here to pass a softer value through."""
    params = list(inspect.signature(admit).parameters)
    assert params == ["candidate"]


def test_no_admission_entry_point_has_a_default_valued_parameter():
    for fn in (admit, admission.flags, admission.automation_state,
               order_by_consistency):
        for p in inspect.signature(fn).parameters.values():
            assert p.default is inspect.Parameter.empty, \
                f"{fn.__name__}({p.name}=) is an override seam"


def test_the_production_constants_are_module_level_and_imported_not_passed():
    assert admission.MIN_ACTIVE_DAYS_90D == 5
    assert admission.PUSH_PER_ACTIVE_DAY_FLAG == 15.0
    assert admission.FORK_FARM_CONCENTRATION == 0.60
    assert admission.FORK_FARM_MIN_REPOS == 8
    assert admission.MASS_SELF_REPO_MIN_REPOS == 30


# --- floor 1: provenance ------------------------------------------------------

def test_zero_provenance_fails_floor_one_with_a_named_reason():
    a = admit(cand(hashes=()))
    assert a.admitted is False
    assert any("provenance" in r and "FAIL" in r for r in a.reasons)


def test_one_signal_satisfies_provenance():
    assert admit(cand(hashes=("abc",))).admitted is True


# --- floor 2: activity is a LABEL, never suppression --------------------------

def test_four_active_days_is_labelled_low_n_and_still_admitted():
    """Court settled Q7/Q8. bcherny, a top roster dev, shows 8 pushes / 4 active days
    purely because his work lands under org repos. Suppressing him would encode an
    attribution limitation as a fact about a person."""
    a = admit(cand(days90=4))
    assert a.low_n is True
    assert a.admitted is True
    assert any("never suppressed" in r for r in a.reasons)


def test_five_active_days_clears_the_activity_floor():
    a = admit(cand(days90=5))
    assert a.low_n is False


def test_zero_activity_is_low_n_and_still_admitted():
    """78 of the real 175-owner pool has zero 90d pushes. Low-n is the DOMINANT case."""
    a = admit(cand(days90=0))
    assert (a.low_n, a.admitted) == (True, True)


def test_the_real_bcherny_row_is_the_low_n_case():
    m = COHORT["bcherny"]
    assert m.pushes == 8 and m.active_days == 4
    assert admit(cand("bcherny", days90=m.active_days)).low_n is True


# --- floor 3: automation ------------------------------------------------------

def test_flagged_is_withheld_not_excluded():
    a = admit(cand(automation="flagged"))
    assert a.admitted is False
    assert a.automation == "flagged"
    assert any("withheld pending human review" in r for r in a.reasons)


def test_excluded_is_out():
    a = admit(cand(automation="excluded"))
    assert a.admitted is False
    assert any("recorded human denylist verdict" in r for r in a.reasons)


def test_a_cleared_candidate_is_admitted_and_its_shapes_stay_visible():
    """Court settled Q7's clearing path: automation_state resolved this to `clear` while
    the shapes still fire, so admit() sees `clear` and the flag evidence is carried on
    the record by the caller. Cleared is transparent, not silent."""
    from cerebro.gitintel.admission import automation_state, flags
    from cerebro.gitintel.denylist import VerdictEntry, Verdicts
    v = Verdicts(cleared={"can1357": VerdictEntry(
        login="can1357", verdict="human", shape="fork_farm",
        evidence="90d: 426 pushes / 38 repos / concentration 0.7368",
        reviewed_by="owner", reviewed_on="2026-08-26")})
    state = automation_state(COHORT["can1357"], "can1357", v)
    assert state == "clear"
    assert admit(cand("can1357", automation=state)).admitted is True
    assert [f.name for f in flags(COHORT["can1357"])] == ["fork_farm"]


# --- floors are INDEPENDENT: no composite -------------------------------------

def test_reasons_carries_exactly_one_line_per_floor_always():
    for c in (cand(), cand(hashes=()), cand(days90=1), cand(automation="flagged")):
        a = admit(c)
        assert len(a.reasons) == 3
        assert a.reasons[0].startswith("provenance:")
        assert a.reasons[1].startswith("activity:")
        assert a.reasons[2].startswith("automation:")


def test_admission_has_no_score_field():
    a = admit(cand())
    assert not hasattr(a, "score")
    assert set(a.__dataclass_fields__) == {"admitted", "low_n", "automation", "reasons"}


def test_a_failing_floor_is_not_offset_by_a_strong_other_floor():
    """The point of independent floors: nothing compensates for anything."""
    strong_but_unprovenanced = cand(hashes=(), days90=90)
    assert admit(strong_but_unprovenanced).admitted is False


# --- F026: cold-cache satisfiability -----------------------------------------

class RecordingCandidate:
    """Traces every attribute admit() reads."""

    def __init__(self):
        self.seen: set[str] = set()
        self._values = {"login": "dev", "signal_hashes": ("a",),
                        "active_days_90d": 10, "active_days_30d": 5,
                        "automation": "clear"}

    def __getattr__(self, name):
        if name in ("seen", "_values"):
            raise AttributeError(name)
        object.__getattribute__(self, "seen").add(name)
        try:
            return object.__getattribute__(self, "_values")[name]
        except KeyError:
            raise AttributeError(name) from None


ALLOWED_FLOOR_INPUTS = {
    "signal_hashes",      # provenance, from the vault lane
    "active_days_90d",    # GH Archive
    "automation",         # tri-state, from shape + recorded verdicts
    "login",
}

FORBIDDEN_SUBSTRINGS = ("follower", "star", "growth", "momentum", "score", "portfolio",
                        "ships", "commits_per_day")


def test_no_floor_reads_a_signal_that_is_structurally_zero_on_a_cold_cache():
    """F026. The previous scorer's follower and portfolio inputs return 0.0 without a
    snapshot >= 7 days old, capping its max at 0.50 against a 0.55 threshold — admission
    was arithmetically impossible on day one. This test traces the ACTUAL attribute
    reads, not a grep."""
    rc = RecordingCandidate()
    admit(rc)
    assert rc.seen <= ALLOWED_FLOOR_INPUTS, f"floor reads {rc.seen - ALLOWED_FLOOR_INPUTS}"
    for name in rc.seen:
        assert not any(bad in name.lower() for bad in FORBIDDEN_SUBSTRINGS)


def test_the_floors_are_satisfiable_on_day_one_data():
    """A candidate with only what one vault note and one ClickHouse row can supply."""
    assert admit(cand(hashes=("note1",), days90=5, days30=3)).admitted is True


# --- T11t: consistency ordering ----------------------------------------------

def test_ordering_is_by_active_days_descending():
    got = order_by_consistency([cand("a", days90=10), cand("b", days90=90),
                                cand("c", days90=50)])
    assert [c.login for c in got] == ["b", "c", "a"]


def test_ties_break_on_thirty_day_activity_then_login():
    got = order_by_consistency([
        cand("zed", days90=50, days30=10),
        cand("amy", days90=50, days30=10),
        cand("bob", days90=50, days30=30),
    ])
    assert [c.login for c in got] == ["bob", "amy", "zed"]


def test_ordering_is_a_total_order_and_byte_stable():
    pool = [cand(f"d{i}", days90=i % 7, days30=i % 3) for i in range(30)]
    assert [c.login for c in order_by_consistency(pool)] == \
        [c.login for c in order_by_consistency(list(reversed(pool)))]


def test_ordering_never_reads_pushes_or_any_volume_field():
    """Checked against the CODE, with the docstring stripped — the prose is allowed to
    say why volume is banned; the executable lines are not allowed to use it."""
    src = inspect.getsource(order_by_consistency)
    code = src.replace(order_by_consistency.__doc__ or "", "")
    for bad in ("pushes", "followers", "stars", "score", "distinct_repos"):
        assert bad not in code, f"volume ranking is INVERTED, not merely noisy: {bad}"


def test_a_flagged_candidate_never_reaches_the_ordered_output():
    """Consistency is NOT an automation discriminator: both day-one denylisted accounts
    sit at the TOP of active-day ranking (90 and 87 of 90 days). Sorting before the
    automation gate would put them at #1 and #2, which is exactly the failure mode the
    gate exists to prevent. Ordering therefore always runs DOWNSTREAM."""
    pool = [
        cand("Dicklesworthstone", days90=90, automation="excluded"),
        cand("diegosouzapw", days90=87, automation="flagged"),
        cand("simonw", days90=66),
        cand("obra", days90=67),
    ]
    admitted = [c for c in pool if admit(c).admitted]
    got = order_by_consistency(admitted)
    assert [c.login for c in got] == ["obra", "simonw"]
    assert "Dicklesworthstone" not in {c.login for c in got}
    assert "diegosouzapw" not in {c.login for c in got}
