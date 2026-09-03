"""F023/F019/F022 — descriptive display facts. Pure arithmetic. No ordering. No thresholds.

THIS MODULE'S DEFINING PROPERTY IS WHAT IT DOES NOT CONTAIN. There is no ordering
function here, no threshold constant, no comparison between two people, and no way to
turn a facet into a filter. That is not restraint, it is the feature: F023's Court note
is that a 54-repo generalist (simonw) and a 2-repo deep-focus dev (t3dotgg) are BOTH
valid shapes, that neither folds into a single axis, and that neither is usable as a
filter. The safest place to enforce "you cannot rank people by this" is a module with
nothing in it capable of ranking.

`distinct_repos` is additionally in `tests/test_no_composite.py`'s `VOLUME_NAMES`, so a
`sorted(..., key=lambda c: c.distinct_repos)` anywhere in the devs lane is already a
build failure. This module hands the site the numbers to PRINT beside a person, in the
same sentence the charter mandates: "shipped 240 commits across 12 repos in 30 days",
never "is more of an engineer than".

WHY BREADTH AND DEPTH ARE RECORDED SEPARATELY AND NEVER COMBINED. Measured on the real
cohort at 90d: simonw is 54 repos at 5.72 pushes/repo, t3dotgg is 2 repos at 45.0,
obra 49 at 8.49, mattpocock 9 at 19.3. Averaging or multiplying those two numbers
produces one figure on which t3dotgg and a fork farm are neighbours. The mishapos shape
(194,964 repos at exactly 1.00 push/repo) sits at one extreme of the SAME axis a human
generalist occupies, which is why depth is a flag input in `admission` and a display
fact here, and a ranking key nowhere.
"""

from __future__ import annotations

from . import shape

#: Every facet this module emits, in render order. Named explicitly so a reader can see
#: the whole surface at once and so e04 can build against a fixed key set. Adding a key
#: is a schema change, which is a coordination event, not a local edit.
FACET_NAMES = (
    "distinct_repos",        # F023 breadth
    "pushes_per_repo",       # F023 depth
    "pushes",
    "active_days",
    "repos_not_owned",       # F019, term 1
    "not_owned_basenames",   # F019, term 2
    "not_owned_owners",      # F019, term 3
)

#: The facets rendered as a rate rather than a count, so a caller formatting them knows
#: which need decimal places without inspecting the values.
RATE_FACETS = ("pushes_per_repo",)


def window_facets(m) -> dict:
    """One window's display facts, as a flat dict of named numbers.

    Every value is a COUNT or a RATE derived from counts. No value is normalised against
    another person, against a cohort, or against a threshold, because any of those three
    would make it comparative — and a comparative number about a named human is a ranking
    whatever it is called.

    F019's triple is recorded WHOLE. `repos_not_owned` alone cannot tell a template bot
    from a prolific contributor (diegosouzapw: 124 not-owned repos, and also 124 distinct
    owners, but only 2 basenames); the three terms side by side can. Emitting one without
    the others would publish the half of the evidence that misleads.
    """
    return {
        "distinct_repos": int(getattr(m, "distinct_repos", 0)),
        "pushes_per_repo": round(shape.pushes_per_repo(m), 4),
        "pushes": int(getattr(m, "pushes", 0)),
        "active_days": int(getattr(m, "active_days", 0)),
        "repos_not_owned": int(getattr(m, "repos_not_owned", 0)),
        "not_owned_basenames": int(getattr(m, "not_owned_basenames", 0)),
        "not_owned_owners": int(getattr(m, "not_owned_owners", 0)),
    }


def facets(windows: dict) -> dict:
    """`{window_days: WindowMetrics}` -> `{"7d": {...}, "30d": {...}, "90d": {...}}`.

    Keyed by the same `"7d"/"30d"/"90d"` strings the frozen record uses, so the site
    renders a facet by name and never by position.

    NOT SORTED, DELIBERATELY. There is no `sorted(` anywhere in this module — not even
    over window keys — so the "e02 adds zero new ordering functions" audit needs no
    exception for this file and a reader needs no judgement call about which sorts are
    innocent. The artifact is byte-stable because the record is serialised with
    `sort_keys=True`, which is where key order belongs.
    """
    return {f"{w}d": window_facets(m) for w, m in windows.items()}


def describe_breadth_and_depth(m) -> str:
    """One factual sentence, in the charter's mandated register.

    Describes the activity, never the person. It contains no adjective about the human,
    no comparison to anybody else, and no word like "prolific", "elite" or "cracked" —
    the owner decision is FACTUAL FRAMING, and this is the string that has to honour it.
    """
    repos = int(getattr(m, "distinct_repos", 0))
    pushes = int(getattr(m, "pushes", 0))
    days = int(getattr(m, "active_days", 0))
    window = int(getattr(m, "window_days", 0))
    if not pushes:
        return f"no pushes attributed in the last {window} days"
    return (f"{pushes} push{'es' if pushes != 1 else ''} across "
            f"{repos} repositor{'ies' if repos != 1 else 'y'} on "
            f"{days} active day{'s' if days != 1 else ''} in the last {window} days")
