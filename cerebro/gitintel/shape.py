"""F014 — recorded shape metrics.

SHAPE, NOT RATE, separates the hard cases. Pure arithmetic on a WindowMetrics, zero
I/O, no thresholds, no verdicts: these four numbers are RECORDED on every candidate
and the flag rules in `admission` read them. Keeping the arithmetic here and the
judgement there is what makes the judgement auditable.

Every docstring below cites the accounts it was calibrated against, measured live on
2026-08-26 at a 90-day window. A division guard returns 0.0 on a zero denominator —
never NaN, never an exception — because 78 of the real 175-owner pool has zero activity
and a zero-activity person is a labelling case, never a crash.
"""

from __future__ import annotations


def push_per_active_day(m) -> float:
    """Pushes per day the account was actually active.

    Calibration (90d): Dicklesworthstone 305.1, diegosouzapw 26.1, koala73 11.85,
    esengine 9.93. Human ceiling measured at sindresorhus 7.14; the next humans down
    are can1357 6.17, santifer 6.42, obra 6.21, Rich-Harris 5.25, simonw 4.68.
    NOTE the two fork farms sit BELOW the 15 flag line — this metric alone catches
    neither koala73 nor esengine, which is why it is never used alone.
    """
    return _ratio(m.pushes, m.active_days)


def repo_per_active_day(m) -> float:
    """Distinct repos touched per active day. Recorded per F014; not a flag input."""
    return _ratio(m.distinct_repos, m.active_days)


def not_owned_ratio(m) -> float:
    """Share of touched repos owned by somebody else.

    Calibration (90d): diegosouzapw 0.954 (124/130, a fork farm) at the top;
    Dicklesworthstone 0.0 (0/109, mass self-repo) at the bottom.
    THIS IS NOT A HUMAN-EXCLUSIVE SHAPE AT EITHER END. paulmillr (28 repos), torvalds,
    antirez and bcherny all sit at exactly 0.0, the same value as Dicklesworthstone.
    A rule keyed on this term alone reaches real humans.
    """
    return _ratio(m.repos_not_owned, m.distinct_repos)


def basename_concentration(m) -> float:
    """Largest same-basename repo group as a share of ALL repos pushed to.

    Defined over every repo touched, not only the not-owned ones — that definition and
    only that one reproduces every published registry figure exactly (santifer 0.8182,
    can1357 0.7368, koala73 1.0000, simonw 0.0556, obra 0.0204).

    THE HUMAN BAND IS WIDE AND ITS TOP IS NOT WHERE IT LOOKS. Bottom: obra 0.0204 over
    49 repos. TOP: Rich-Harris 0.5385 over 26 repos, measured live 2026-08-26 — NOT
    simonw's 0.0556, which an earlier draft wrongly called the ceiling. And t3dotgg
    scores a perfect 1.0000 because both his repos are named `t3code`, while
    Dicklesworthstone — the worst account in the pool — scores the LOWEST value measured,
    0.0092. This metric alone catches a human and misses the spammer; it is only usable
    behind a minimum-repo-count guard.
    """
    return _ratio(m.max_basename_group, m.distinct_repos)


def pushes_per_repo(m) -> float:
    """Pushes per distinct repo. F012's synthetic-repo shape (mishapos: 194,964 repos
    at exactly 1.00). Human minimum measured: wesbos 1.50, ljharb 2.65."""
    return _ratio(m.pushes, m.distinct_repos)


def _ratio(num, den) -> float:
    if not den:
        return 0.0
    return float(num) / float(den)
