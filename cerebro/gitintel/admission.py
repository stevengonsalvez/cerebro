"""F010/F012/F014/F018/F025/F026 — flags, floors and ordering.

THREE THINGS LIVE HERE, AND NONE OF THEM IS A SCORE.

1. `flags()` — every automation SHAPE that fires on a candidate. It returns a list,
   never a boolean and never a verdict, and it NEVER excludes anybody.
2. `admit()` — three INDEPENDENT floors, evaluated and reported separately. No weights,
   no sum, no single ranking number, no league table. Court settled Q2.
3. `order_by_consistency()` — the default facet sort. Active days, not volume: the
   charter's central design constraint is that GH Archive volume ranking is INVERTED,
   not merely noisy.

WHY THERE ARE NO THRESHOLD KEYWORD ARGUMENTS ANYWHERE IN THIS MODULE. The scorer this
replaces shipped broken for six production runs because every one of its admission
tests overrode the real 0.55 threshold with 0.02, so nothing ever exercised the value
that actually ran. Constants here are module-level and tests import them. A test cannot
pass a softer value because there is no parameter to pass it through — the defect class
is unrepresentable, not merely absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from . import shape

AutomationState = Literal["clear", "flagged", "excluded"]

# --- flag constants ---------------------------------------------------------
# Every one of these was calibrated against live 90d measurements taken 2026-08-26.
# Each comment names BOTH the account the rule must catch and the account it must not.

PUSH_PER_ACTIVE_DAY_FLAG = 15.0
"""Court settled Q1. FLAG FOR REVIEW ONLY, never an auto-exclude and never alone.

Human ceiling measured at sindresorhus 7.14 over the 16-account s2 cohort. On the real
pool the distribution is CONTINUOUS at this point (14.52 and 14.45 immediately below,
25.85 immediately above; 2 of 87 active owners above it), which is precisely why it
cannot be a threshold: a knife-edge moves people across the line on noise. It is also
insufficient in the other direction — koala73 is a fork farm at 11.85 and esengine at
9.93, both BELOW the line.
"""

MASS_SELF_REPO_MIN_REPOS = 30
"""THE ONLY THING BETWEEN THIS RULE AND A REAL HUMAN. Calibrate it, not the rate.

Catches: Dicklesworthstone 109 repos / 0 not-owned / 308.49 ppd, and mvanhorn 204 repos
/ 4 not-owned / 8.84 ppd — both measured live 90d, and note the 35x spread in push rate
between them. Highest human measured on this shape: paulmillr at 28 repos, ratio 0.0000
(s2 cohort). Next-highest in the real 159-account active pool: Leonxlnx at 17 repos.
The measured band 29..108 is EMPTY of humans in both cohorts, which is what makes 30
defensible — but the headroom over paulmillr is TWO REPOS, so lowering this reaches a
real prolific engineer immediately. Do not lower it.
"""

NOT_OWNED_RATIO_SELF_MAX = 0.05
"""WHAT PROTECTS HUMANS HERE IS THE REPO-COUNT CONJUNCT, NOT THIS TERM.

paulmillr (28 repos), torvalds, antirez and bcherny all sit at not_owned_ratio EXACTLY
0.0 — measured live 2026-08-26 — the same value as Dicklesworthstone. They are kept
clear by `>= 30 repos` alone. 0.05 rather than == 0.0 so that one push to one not-owned
repo does not buy an escape; mvanhorn passes it at 4/204 = 0.0196.
"""

FORK_FARM_MIN_REPOS = 8
"""t3dotgg: basename concentration 1.0000 over 2 repos — A REAL HUMAN, and the highest
concentration measured anywhere including the fork farms. Both his repos are named
`t3code` (pingdotgg/t3code, thomaslittle/t3code). torvalds (0.5000/2), ryanflorence
(0.5000/2), antirez (0.5000/2) and bcherny (1.0000/1) are all held clear by this guard
too. It exists solely to keep them out. DO NOT LOWER IT.
"""

FORK_FARM_CONCENTRATION = 0.60
"""Fires live at: koala73 1.0000/24, diegosouzapw 0.9538/130, santifer 0.8182/44,
can1357 0.7368/38, esengine 0.7273/11.

NEAREST-MISS HUMAN: Rich-Harris 0.5385 over 26 repos, measured live 2026-08-26 — 0.0615
of headroom, about 11%. The real human ceiling on concentration is 0.5385, NOT simonw's
0.0556; the "gap 0.73 -> 0.056" figure some earlier notes carry is FALSE. Next humans
down: gaearon 0.2857/7, addyosmani 0.1429/7, mattpocock 0.1111/9, ljharb 0.1077/65,
simonw 0.0556/54, sindresorhus 0.0392/51, paulmillr 0.0357/28, kentcdodds 0.0233/43,
obra 0.0204/49. LOWERING THIS BELOW 0.5385 FLAGS RICH-HARRIS; a test pins his row.
"""

SYNTHETIC_REPO_MIN_REPOS = 50
"""F012, the mishapos shape: 194,964 repos at exactly 1.00 push per repo."""

SYNTHETIC_PUSH_PER_REPO = 1.2
"""Human minimum measured: wesbos 1.50, ljharb 2.65 (at 65 repos, the only s2 human
above the 50-repo guard alongside obra 8.49 and simonw 5.72)."""

#: The `fork_farm` sub-shapes. ALL THREE ARE FLAGS. All three enter the review queue.
#: NONE of them clears anybody, and `automation_state()` below is untouched: `excluded`
#: stays reachable only from `verdicts.denied` and `clear` only from nothing-firing or a
#: recorded `cleared:` verdict.
#:
#: THE SEPARATOR e01 ASKED FOR DOES NOT EXIST, AND THAT IS WHY THESE ARE NAMES AND NOT
#: DECISIONS. e01's denylist header predicted that "forks of an upstream the person also
#: authors" would separate a maintainer from a fork farm. Measured live: koala73
#: (cleared: human) and diegosouzapw (denied: automation) BOTH return own_upstream 5,
#: third_party 0, and both upstreams are non-fork repos the candidate owns
#: (koala73/worldmonitor 84,341 stars; diegosouzapw/OmniRoute 56,206 stars). A rule that
#: cleared one would clear the other. `tests/test_admission_flags.py` pins the equality
#: so no future editor re-derives a separator that is not there.
#:
#: What the sub-shape buys is a CHEAPER, BETTER-INFORMED human decision: the reviewer
#: reads "forks of diegosouzapw/OmniRoute, itself not a fork" instead of a bare
#: concentration ratio. The decision stays theirs.
FORK_SUBSHAPES = ("fork_farm_own_upstream", "fork_farm_third_party",
                  "fork_farm_no_upstream")

@dataclass(frozen=True)
class Flag:
    """One automation shape that fired, carrying the numbers that fired it."""

    name: str
    evidence: str
    metric_values: dict = field(default_factory=dict)


def flags(m90) -> list[Flag]:
    """EVERY shape that fires on a 90-day WindowMetrics. Never excludes anybody.

    Returns a list, so a lone `high_push_rate` is a flag among possible others and can
    never be read as a verdict. The rules are deliberately SEPARATE and not collapsible:
    Dicklesworthstone is 109 repos with ZERO not-owned at concentration 0.0092;
    diegosouzapw is 130 repos with 124 not-owned at concentration 0.9538. They are
    opposite shapes. Any single predicate wide enough to cover both swallows the entire
    human band between them.

    THE SIGNATURE IS DELIBERATELY UNCHANGED FROM e01 AND TAKES NO KEYWORD. Two tests
    (`test_flags_and_automation_state_take_no_threshold_kwargs`,
    `test_no_admission_entry_point_has_a_default_valued_parameter`) forbid every
    default-valued parameter on this function, because the scorer this replaces shipped
    broken for six production runs behind exactly such an override seam. e02's fork
    provenance is therefore applied by `name_fork_subshape()` AFTER this function
    returns, rather than by growing a `fork_evidence=None` keyword here. Metrics in,
    shapes out; refining a shape's NAME from external evidence is a separate step.
    """
    out: list[Flag] = []
    ppd = shape.push_per_active_day(m90)
    repos = m90.distinct_repos
    ratio = shape.not_owned_ratio(m90)
    conc = shape.basename_concentration(m90)
    ppr = shape.pushes_per_repo(m90)
    values = {
        "push_per_active_day": round(ppd, 4),
        "repo_per_active_day": round(shape.repo_per_active_day(m90), 4),
        "not_owned_ratio": round(ratio, 4),
        "basename_concentration": round(conc, 4),
        "pushes_per_repo": round(ppr, 4),
        "distinct_repos": repos,
        "active_days_90d": m90.active_days,
        "pushes_90d": m90.pushes,
    }

    if ppd > PUSH_PER_ACTIVE_DAY_FLAG:
        out.append(Flag(
            "high_push_rate",
            f"{ppd:.2f} pushes per active day over 90d "
            f"({m90.pushes} pushes / {m90.active_days} active days), "
            f"above the {PUSH_PER_ACTIVE_DAY_FLAG:g} review line",
            values,
        ))

    # SHAPE, NOT RATE. This rule carried `ppd > PUSH_PER_ACTIVE_DAY_FLAG` as a third
    # conjunct until 2026-08-26, which made it strictly narrower than `high_push_rate`
    # and therefore incapable of detecting anything that rule had not already caught —
    # a shape rule with zero detection power of its own. The live nearest-miss proves
    # the cost: mvanhorn, 204 distinct repos with 200 of them his own, cleared every
    # mechanical filter at 8.84 pushes per active day and reached the top-20 with an
    # empty flag list. The Court settled that shape, not rate, separates the hard cases;
    # the rate line is PAIRED WITH shape metrics, never a gate in front of them.
    if repos >= MASS_SELF_REPO_MIN_REPOS and ratio <= NOT_OWNED_RATIO_SELF_MAX:
        out.append(Flag(
            "mass_self_repo",
            f"{repos} distinct repos, {m90.repos_not_owned} not owned "
            f"(ratio {ratio:.4f}), {ppd:.2f} pushes per active day",
            values,
        ))

    if repos >= FORK_FARM_MIN_REPOS and conc >= FORK_FARM_CONCENTRATION:
        out.append(Flag(
            "fork_farm",
            f"basename concentration {conc:.4f} "
            f"({m90.max_basename_group} of {repos} repos share one basename), "
            f"{m90.repos_not_owned} not owned across "
            f"{m90.not_owned_basenames} basenames",
            values,
        ))

    if repos >= SYNTHETIC_REPO_MIN_REPOS and ppr <= SYNTHETIC_PUSH_PER_REPO:
        out.append(Flag(
            "synthetic_repo",
            f"{ppr:.2f} pushes per repo across {repos} repos "
            f"— one-push-per-repo fan-out",
            values,
        ))

    return out


def name_fork_subshape(fired, fork_evidence):
    """Refine a fired `fork_farm` flag's NAME using fork provenance. Returns a new list.

    A SEPARATE FUNCTION RATHER THAN A KEYWORD ON `flags()`, on purpose. e01 forbids every
    default-valued parameter on the admission entry points because the condemned scorer
    shipped broken behind an override seam of exactly that shape, and that guard is worth
    more than the convenience of one keyword. Splitting the step also states the real
    decomposition: `flags()` derives shapes from metrics, this derives a more precise
    NAME from evidence gathered elsewhere.

    IT RENAMES. IT NEVER ADDS, REMOVES, CLEARS OR EXCLUDES. The returned list has the
    same length and the same order, `automation_state()` reads the same predicate it
    always did, and every sub-shape is a flag that enters the review queue exactly as the
    bare `fork_farm` would have.

    Incomplete evidence — no evidence at all, a partial sample, an unresolved REST call,
    an exhausted budget, or a genuinely mixed result — leaves the bare name standing. That
    direction is the safe one: the bare flag still routes the account to a human, so
    falling back costs a reviewer some context and costs nobody a wrong automatic outcome.
    A flag is never renamed to a sub-shape it did not earn.
    """
    sub = _subshape_name(fork_evidence)
    if not sub:
        return list(fired)
    from .fork_provenance import describe
    detail = describe(fork_evidence)
    return [
        Flag(sub, f"{f.evidence} — {detail}", f.metric_values)
        if f.name == "fork_farm" else f
        for f in fired
    ]


def _subshape_name(ev) -> str | None:
    """The precise sub-shape name, or None to leave the bare `fork_farm` standing.

    Every branch returns a FLAG NAME. There is no branch that returns "clear", none that
    returns "excluded", and none that returns a boolean.
    """
    if ev is None or not getattr(ev, "complete", False):
        return None
    if ev.third_party > 0:
        # Any sample forking somebody else's repo is the shape worth naming, whatever
        # else is in the sample.
        return "fork_farm_third_party"
    if ev.own_upstream == ev.checked and ev.checked > 0:
        return "fork_farm_own_upstream"
    if ev.no_upstream == ev.checked and ev.checked > 0:
        return "fork_farm_no_upstream"
    return None


def automation_state(m90, login: str, verdicts) -> AutomationState:
    """Tri-state. `excluded` is reachable ONLY from `verdicts.denied`.

    No arithmetic path leads to `excluded`; every exclusion is a recorded human verdict.
    `clear` is reachable TWO ways, per Court settled Q7's "clear, or flagged-then-
    resolved-clear by human review":
      · nothing fired, or
      · shapes fired AND a human recorded a `cleared:` verdict.

    The second route is not a nicety. Without it a human-reviewed real engineer whose
    shapes still fire is re-flagged identically on every run and withheld for ever —
    arithmetic suppression of a person a human explicitly cleared, arriving through the
    back door. It is also what makes "re-run until the queue is empty" terminate.
    A cleared candidate still carries its firing shapes as evidence: cleared is
    transparent, not silent.
    """
    key = (login or "").strip().lower()
    if key in verdicts.denied:
        return "excluded"
    if not flags(m90):
        return "clear"
    if key in verdicts.cleared:
        return "clear"
    return "flagged"


# --- floors -----------------------------------------------------------------

MIN_ACTIVE_DAYS_90D = 5
"""Court settled Q7. Below this the candidate gets the `low_n` LABEL and is still
admitted — suppression is forbidden. Low-n is the pool's DOMINANT case (78 of 175
owners have zero 90d pushes), and bcherny, a top roster dev, shows 8 pushes / 4 active
days purely because his work lands under org repos not attributed to his personal
actor. That is an attribution limitation, never a fact about a person.
"""


@dataclass(frozen=True)
class Candidate:
    """Everything the floors read. Deliberately narrow: see `admit`'s F026 note."""

    login: str
    signal_hashes: tuple[str, ...]
    active_days_90d: int
    active_days_30d: int = 0
    automation: AutomationState = "clear"


@dataclass(frozen=True)
class Admission:
    admitted: bool
    low_n: bool
    automation: AutomationState
    reasons: tuple[str, ...]


def admit(candidate) -> Admission:
    """Three independent floors, reported separately. NO THRESHOLD KWARGS, BY DESIGN.

    1. PROVENANCE — at least one vault signal. Answers "why is this person here" for
       every published profile.
    2. ACTIVITY — >= 5 active days in 90d, else the `low_n` LABEL. `admitted` stays
       True: the label is the mechanism and suppression is forbidden (Court Q7/Q8).
    3. AUTOMATION — `clear` admits, `flagged` withholds pending human review,
       `excluded` (a recorded `denied:` verdict only) is out.

    F026: no floor reads any signal that is structurally zero on a cold cache. There is
    no follower, star, growth, momentum or score input here — those are exactly what
    made the previous scorer's 0.55 threshold arithmetically unreachable on day one.

    No weights. No sum. No score. `reasons` is the audit trail the transparency page
    needs: one line per floor, pass or fail, always populated.
    """
    reasons: list[str] = []

    provenance_ok = len(candidate.signal_hashes) >= 1
    reasons.append(
        f"provenance: {len(candidate.signal_hashes)} vault signal(s) — "
        f"{'pass' if provenance_ok else 'FAIL, no originating signal note'}"
    )

    low_n = candidate.active_days_90d < MIN_ACTIVE_DAYS_90D
    reasons.append(
        f"activity: {candidate.active_days_90d} active days in 90d — "
        + (f"below the {MIN_ACTIVE_DAYS_90D}-day line, LABELLED low-n (never suppressed)"
           if low_n else "pass")
    )

    state = candidate.automation
    reasons.append(
        "automation: " + {
            "clear": "clear — pass",
            "flagged": "FLAGGED, withheld pending human review",
            "excluded": "EXCLUDED by a recorded human denylist verdict",
        }[state]
    )

    admitted = provenance_ok and state == "clear"
    return Admission(admitted=admitted, low_n=low_n, automation=state,
                     reasons=tuple(reasons))


def order_by_consistency(candidates):
    """The default facet sort: CONSISTENCY, never volume.

    active_days_90d desc, tie-break active_days_30d desc, then login asc so the artifact
    is byte-stable run to run. This is a facet sort, not a ranking number — there is no
    score to sort by and none is computed anywhere in this module.

    ORDERING ALWAYS RUNS DOWNSTREAM OF THE AUTOMATION GATE, because consistency is NOT
    an automation discriminator: both day-one denylisted accounts sit at the TOP of
    active-day ranking (90 and 87 of 90 days). Sorting first would put them at #1 and #2.
    """
    return sorted(
        candidates,
        key=lambda c: (-int(c.active_days_90d), -int(c.active_days_30d), c.login.lower()),
    )
