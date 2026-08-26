"""F010/F012/F014/F018/F025/F026 — flags, floors and ordering.

NOTHING THAT LIVES HERE IS A SCORE.

1. `flags()` — every automation SHAPE that fires on a candidate. It returns a list,
   never a boolean and never a verdict, and it NEVER excludes anybody.
2. the admission floors and the default facet sort, which land in the next commit.

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
"""Dicklesworthstone: 109 repos, 0 not-owned, 308.5 push-per-active-day (90d, live).

THIS CONJUNCT IS WHAT PROTECTS HUMANS, together with the push-rate one. paulmillr sits
at 28 repos. Lower this and the rule starts reaching real prolific engineers.
"""

NOT_OWNED_RATIO_SELF_MAX = 0.05
"""WHAT PROTECTS HUMANS HERE IS THE CONJUNCTION, NOT THIS TERM.

paulmillr (28 repos), torvalds, antirez and bcherny all sit at not_owned_ratio EXACTLY
0.0 — measured live 2026-08-26 — the same value as Dicklesworthstone. They are kept
clear by `>= 30 repos` AND `> 15 push/active-day` (paulmillr: 28 repos, 3.22 ppd), never
by the ratio. Drop either conjunct and the rule reaches real humans. 0.05 rather than
== 0.0 so that one push to one not-owned repo does not buy an escape.
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

    if (repos >= MASS_SELF_REPO_MIN_REPOS
            and ratio <= NOT_OWNED_RATIO_SELF_MAX
            and ppd > PUSH_PER_ACTIVE_DAY_FLAG):
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
