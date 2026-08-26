"""T08t — F010/F012/F014 automation flags, tri-state, at PRODUCTION constants.

Every row in COHORT is a LIVE 90-day measurement taken 2026-08-26 against
play.clickhouse.com over the real calibration cohort, parsed from the committed
fixture. This table is executable documentation: if a constant moves, the row that
guards it fails by name.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from cerebro.gitintel import admission
from cerebro.gitintel.admission import Flag, automation_state, flags
from cerebro.gitintel.denylist import EMPTY, VerdictEntry, Verdicts
from cerebro.gitintel.gharchive import _parse_tsv

FIXTURE = Path(__file__).parent / "fixtures" / "gharchive_cohort_90d.tsv"
COHORT = _parse_tsv(FIXTURE.read_text(encoding="utf-8"), 90)

#: The 16-account s2 human cohort. More than ONE flagged here is kill criterion 3.
S2_HUMANS = (
    "sindresorhus", "simonw", "kentcdodds", "gaearon", "mattpocock", "t3dotgg",
    "paulmillr", "Rich-Harris", "ljharb", "torvalds", "ryanflorence", "addyosmani",
    "jherr", "antirez", "wesbos", "obra",
)


def names(login: str) -> set[str]:
    return {f.name for f in flags(COHORT[login])}


def _entry(login, shape="fork_farm", verdict="human"):
    return VerdictEntry(login=login, verdict=verdict, shape=shape,
                        evidence="reviewed by hand", reviewed_by="owner",
                        reviewed_on="2026-08-26")


# --- the two hard cases, which are OPPOSITE shapes ---------------------------

def test_dicklesworthstone_is_mass_self_repo():
    assert names("Dicklesworthstone") == {"high_push_rate", "mass_self_repo"}


def test_diegosouzapw_is_a_fork_farm():
    assert names("diegosouzapw") == {"high_push_rate", "fork_farm"}


def test_the_two_hard_cases_share_no_shape_but_high_push_rate():
    d = names("Dicklesworthstone") - {"high_push_rate"}
    f = names("diegosouzapw") - {"high_push_rate"}
    assert d and f and not (d & f), "one predicate covering both would swallow the humans between"


# --- the flag path is not threshold-only -------------------------------------

def test_koala73_is_flagged_below_the_push_rate_line():
    """The Court's proof: a fork farm at 11.85 push/active-day, under the 15 line."""
    assert names("koala73") == {"fork_farm"}
    assert "high_push_rate" not in names("koala73")


def test_esengine_is_flagged_below_the_push_rate_line():
    assert names("esengine") == {"fork_farm"}


def test_can1357_and_santifer_are_flagged_by_concentration_alone():
    assert names("can1357") == {"fork_farm"}
    assert names("santifer") == {"fork_farm"}


# --- the guards that keep real humans out ------------------------------------

def test_t3dotgg_is_clear_despite_a_perfect_concentration():
    """The finding that shapes the filter: a real human at concentration 1.0000,
    higher than any fork farm, because both his repos are named `t3code`."""
    from cerebro.gitintel.shape import basename_concentration
    assert basename_concentration(COHORT["t3dotgg"]) == pytest.approx(1.0)
    assert names("t3dotgg") == set()


def test_rich_harris_is_the_nearest_miss_human_and_stays_clear():
    """THE HUMAN CEILING ON CONCENTRATION IS 0.5385, NOT simonw's 0.0556.

    26 repos is well past the 8-repo guard, and 0.5385 is only 0.0615 under the 0.60
    line — about 11% of headroom. Any future change to FORK_FARM_CONCENTRATION must
    leave this row green."""
    from cerebro.gitintel.shape import basename_concentration
    m = COHORT["Rich-Harris"]
    assert m.distinct_repos == 26 > admission.FORK_FARM_MIN_REPOS
    assert basename_concentration(m) == pytest.approx(0.5385, abs=0.02)
    assert basename_concentration(m) < admission.FORK_FARM_CONCENTRATION
    assert names("Rich-Harris") == set()


def test_paulmillr_is_the_mass_self_repo_counter_example():
    """not_owned_ratio == 0.0 IS NOT A HUMAN-EXCLUSIVE SHAPE. paulmillr sits at exactly
    the same ratio as Dicklesworthstone, so the ratio term protects nobody. The ONLY
    thing holding him clear is the repo-count conjunct, and the margin is TWO REPOS.
    Lower MASS_SELF_REPO_MIN_REPOS and this test names the human you reached."""
    from cerebro.gitintel.shape import not_owned_ratio
    m = COHORT["paulmillr"]
    assert not_owned_ratio(m) == 0.0
    assert not_owned_ratio(COHORT["Dicklesworthstone"]) == 0.0   # identical ratio
    assert m.distinct_repos == 28 < admission.MASS_SELF_REPO_MIN_REPOS
    assert names("paulmillr") == set()


def test_mvanhorn_is_flagged_below_the_push_rate_line():
    """THE REGRESSION THIS RULE WAS REWRITTEN FOR. mass_self_repo used to carry
    `push_per_active_day > 15` as a third conjunct, which made it strictly narrower
    than high_push_rate and unable to detect anything that rule had not already caught.
    mvanhorn — 204 distinct repos, 200 of them his own, at 8.84 pushes per active day —
    walked through every mechanical filter with an EMPTY flag list and reached the
    published top-20 unreviewed. Live 90d measurement, 2026-08-26.

    He is a real named engineer (Matt Van Horn, GitHub user since 2010, 4,901 followers)
    and carries a `cleared:` verdict in config/devs_denylist.yaml. That is the point:
    the shape is now DETECTED and the resolution is a recorded human verdict, instead
    of the account passing silently."""
    from cerebro.gitintel.shape import not_owned_ratio, push_per_active_day
    m = COHORT["mvanhorn"]
    assert m.distinct_repos == 204
    assert push_per_active_day(m) == pytest.approx(8.84, abs=0.01)
    assert push_per_active_day(m) < admission.PUSH_PER_ACTIVE_DAY_FLAG   # under the line
    assert not_owned_ratio(m) == pytest.approx(0.0196, abs=0.001)
    assert names("mvanhorn") == {"mass_self_repo"}


def test_mass_self_repo_can_fire_without_high_push_rate():
    """A shape rule that can only fire when a rate rule has already fired has zero
    detection power. Asserted structurally, over the whole cohort, so the conjunct
    cannot be reintroduced as a 'safety tightening'."""
    rate_free = [login for login in COHORT
                 if "mass_self_repo" in names(login) and "high_push_rate" not in names(login)]
    assert rate_free, "mass_self_repo fires only alongside high_push_rate — it detects nothing"


def test_torvalds_antirez_bcherny_also_sit_at_ratio_zero_and_stay_clear():
    from cerebro.gitintel.shape import not_owned_ratio
    for login in ("torvalds", "antirez", "bcherny"):
        assert not_owned_ratio(COHORT[login]) == 0.0
        assert names(login) == set()


def test_ljharb_and_obra_clear_the_synthetic_repo_guard():
    """Both are above the 50-repo line; the push-per-repo conjunct is what clears them."""
    from cerebro.gitintel.shape import pushes_per_repo
    for login in ("ljharb", "obra", "simonw", "sindresorhus"):
        m = COHORT[login]
        if m.distinct_repos >= admission.SYNTHETIC_REPO_MIN_REPOS:
            assert pushes_per_repo(m) > admission.SYNTHETIC_PUSH_PER_REPO
        assert "synthetic_repo" not in names(login)


# --- the false-positive floor (kill criterion 3) -----------------------------

@pytest.mark.parametrize("login", S2_HUMANS)
def test_every_s2_human_is_clear_at_production_constants(login):
    assert names(login) == set(), f"{login} flagged — kill criterion 3 is >1 of these"


def test_zero_human_false_positives_in_total():
    flagged = [x for x in S2_HUMANS if names(x)]
    assert flagged == [], f"a filter that flags real engineers is worse than no filter: {flagged}"


# --- flags() never excludes --------------------------------------------------

def test_flags_returns_a_list_never_a_verdict():
    for login in COHORT:
        got = flags(COHORT[login])
        assert isinstance(got, list)
        assert all(isinstance(f, Flag) for f in got)


def test_every_flag_carries_numeric_evidence():
    for login in COHORT:
        for f in flags(COHORT[login]):
            assert f.evidence.strip()
            assert any(ch.isdigit() for ch in f.evidence)
            assert f.metric_values["distinct_repos"] == COHORT[login].distinct_repos


def test_a_lone_high_push_rate_yields_flagged_not_excluded():
    from cerebro.gitintel.gharchive import WindowMetrics
    m = WindowMetrics(window_days=90, pushes=1000, distinct_repos=3, active_days=10,
                      repos_not_owned=1, not_owned_basenames=1, max_basename_group=1)
    assert {f.name for f in flags(m)} == {"high_push_rate"}
    assert automation_state(m, "someone", EMPTY) == "flagged"


def test_zero_activity_never_crashes_and_never_flags():
    from cerebro.gitintel.gharchive import WindowMetrics
    m = WindowMetrics(window_days=90)
    assert flags(m) == []
    assert automation_state(m, "quiet-person", EMPTY) == "clear"


# --- tri-state ---------------------------------------------------------------

def test_excluded_is_unreachable_without_a_denied_verdict():
    """No arithmetic path leads to `excluded`, over the WHOLE cohort, not one case."""
    for login, m in COHORT.items():
        assert automation_state(m, login, EMPTY) in ("clear", "flagged")


def test_excluded_comes_only_from_the_denied_section():
    v = Verdicts(denied={"dicklesworthstone": _entry("Dicklesworthstone",
                                                     "mass_self_repo", "automation")})
    assert automation_state(COHORT["Dicklesworthstone"], "Dicklesworthstone", v) == "excluded"
    assert automation_state(COHORT["diegosouzapw"], "diegosouzapw", v) == "flagged"


def test_a_cleared_login_resolves_to_clear_even_while_its_shapes_fire():
    """Court settled Q7's clearing path. can1357 (Can Boluk, a well-known reverse
    engineer) fires fork_farm at 0.7368 over 38 repos. Without a durable clearing
    verdict he is re-flagged and withheld on every run for ever."""
    assert names("can1357") == {"fork_farm"}
    assert automation_state(COHORT["can1357"], "can1357", EMPTY) == "flagged"
    v = Verdicts(cleared={"can1357": _entry("can1357")})
    assert automation_state(COHORT["can1357"], "can1357", v) == "clear"
    # and the evidence survives the clearing — cleared is transparent, not silent
    assert flags(COHORT["can1357"])


def test_verdict_lookup_is_case_insensitive_in_both_sections():
    v = Verdicts(denied={"dicklesworthstone": _entry("Dicklesworthstone")},
                 cleared={"can1357": _entry("can1357")})
    assert automation_state(COHORT["Dicklesworthstone"], "DICKLESWORTHSTONE", v) == "excluded"
    assert automation_state(COHORT["can1357"], "CAN1357", v) == "clear"


# --- F068: the override defect class is unrepresentable ----------------------

def test_flags_and_automation_state_take_no_threshold_kwargs():
    """The scorer this replaces shipped broken for six runs because every admission
    test overrode 0.55 with 0.02. A test cannot soften these constants because there
    is no parameter to pass one through."""
    for fn in (flags, automation_state):
        for p in inspect.signature(fn).parameters.values():
            assert p.kind is not p.KEYWORD_ONLY, f"{fn.__name__} grew a kwarg: {p.name}"
            assert p.default is inspect.Parameter.empty, \
                f"{fn.__name__}({p.name}=) is an override seam"
