"""F027 — "ships" reframed as portfolio FRESHNESS: a date and three counts.

WHAT IS NOT PORTED, AND WHY IT CANNOT BE. `crackscore._ships_score` is
`volume * 0.5 + recency * 0.3 + young_high_output * 0.2` — a weighted composite of a
volume term and an ACCOUNT-AGE bonus. Two separate rulings kill it: no composite score
exists anywhere in this system, and a young-account bonus is a judgement about a person
rather than a fact about their work. Porting it and renaming the variable would satisfy
the letter of the sweep and violate the ruling; the Court's own words are "reframed as a
FACT/facet, not a score input".

So this module emits four facts, from `repos[]` that the e03 repo lane ALREADY fetched:

    last_push_at        the newest push date across the dev's own non-fork repos
    repos_pushed_30d    how many of those were pushed in the last 30 days
    repos_pushed_90d    ... and the last 90
    repos_considered    THE DENOMINATOR, and the field that makes the rest honest

MARGINAL REST COST: ZERO, asserted by a client counter delta rather than by inspection.

`repos_considered: 0` WITH NULL COUNTS IS "NOT FETCHED", NOT "SHIPS NOTHING". A dev the
repo lane never reached — budget exhausted, a call that raised, a profile withheld — must
never be described by a zero, because a zero beside a named human reads as a fact about
them. `repos_populated: false` therefore produces nulls, and the difference is preserved
all the way into the artifact.

Nothing here is normalised against anybody else, and no number here orders anybody.
"""

from __future__ import annotations

import datetime as dt

#: The two windows the counts are taken over. The same 30/90 the free lane uses, so a
#: reader is never comparing a 28-day number with a 30-day one.
RECENT_WINDOWS = (30, 90)


def freshness(repos, *, populated: bool, now=None) -> dict:
    """Four facts about one dev's own repos. Pure, total, and free.

    `populated` is the e03 repo lane's `repos_populated`: it says whether anybody LOOKED,
    which is a different question from what they found.
    """
    if not populated:
        return {
            "fetched": False,
            "repos_considered": 0,
            "last_push_at": None,
            "repos_pushed_30d": None,
            "repos_pushed_90d": None,
        }

    rows = list(repos or ())
    dates = [_parse(_get(row, "last_push")) for row in rows]
    dates = [d for d in dates if d is not None]
    today = _today(now)
    out = {
        "fetched": True,
        "repos_considered": len(rows),
        "last_push_at": max(dates).isoformat() if dates else None,
    }
    for window in RECENT_WINDOWS:
        cutoff = today - dt.timedelta(days=window)
        out[f"repos_pushed_{window}d"] = sum(1 for d in dates if d >= cutoff)
    return out


def report(records, *, now=None) -> dict:
    """`{login: freshness(...)}` over the records this run produced.

    Reads `repos` and `repos_populated` off each record and touches no client at all, so
    the lane's REST delta is structurally 0 rather than incidentally 0.
    """
    out = {}
    for record in records or ():
        login = str(_get(record, "login", "") or "")
        if not login:
            continue
        out[login] = freshness(_get(record, "repos") or (),
                               populated=bool(_get(record, "repos_populated", False)),
                               now=now)
    return out


def census_line(payload: dict) -> str:
    """One sentence for the lane census, with the not-fetched half named rather than
    folded into a zero."""
    total = len(payload)
    fetched = sum(1 for entry in payload.values() if entry.get("fetched"))
    with_push = sum(1 for entry in payload.values() if entry.get("last_push_at"))
    return (f"freshness: {fetched} of {total} record(s) carry fetched repos, "
            f"{with_push} report a newest push date; the rest read as NOT FETCHED, "
            f"never as zero")


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _today(now):
    if now is None:
        return dt.date.today()
    if callable(now):
        now = now()
    return now.date() if isinstance(now, dt.datetime) else now


def _parse(value):
    """`2026-08-24` or a full ISO timestamp -> `date`, else None. Total.

    An unparseable date is dropped rather than defaulted: a wrong newest-push date on a
    named person's page is the charter's wrong-number class, and one fewer repo in a
    count is not.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None
