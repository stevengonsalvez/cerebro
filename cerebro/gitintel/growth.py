"""F024 — growth as a DELTA OF ACTIVE DAYS, or nothing at all.

`None` IS THE WHOLE DESIGN. `metrics.py:118-138` returns `0.0` when there is no snapshot
old enough to compare against, and that structural zero is exactly how admission became
arithmetically impossible in the condemned scorer: two of four weighted terms were 0 on
every cold cache, the reachable maximum was 0.50, and the threshold was 0.55. A number
that means "we could not measure this" must never be spendable as a number that means
"this person did not do anything".

So this module answers with a `Delta` or with `None`, and the artifact writes JSON `null`
beside a reason naming the day count. A test asserts `0.0` never appears in the
insufficient-history shape.

WHAT IS COMPARED, AND WHAT IS DELIBERATELY NOT. Active days today minus active days at the
baseline, over the same window. Nothing else:

    no growth_score, no momentum, no acceleration, no log terms, no weights
    no import of `metrics` (the sweep's BANNED_IMPORTS already forbids it)
    `admission` never imports this module, asserted

A DELTA OF ACTIVE DAYS IS SIGNED AND MAY LEGITIMATELY BE NEGATIVE. Somebody shipped on
fewer days this month than last, which is a fact about a month and not a judgement about a
person. It is recorded with its baseline date beside it. It is never a floor, never a
filter, never an ordering key.

The clock starts when F057 writes the first snapshot, not when this module lands: on the
first run every login reads `insufficient history: 0 of 7 days`, and that is correct
output, not a failure.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

#: Below this much history there is no answer, only `None`. Seven days is the Court's
#: hard condition on F024 ("structurally zero until >=7 days of self-written history").
MIN_HISTORY_DAYS = 7

#: How far back the baseline is taken from when history allows. The prune policy's
#: `SNAPSHOT_RETAIN_DAILY_DAYS` is asserted against this by test, so retention can never
#: silently shrink below what this module reads.
LOOKBACK_DAYS = 30

#: The one window growth is read over. The 90-day window moves too slowly to say anything
#: in a month and the 7-day window is mostly weekday noise.
DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Delta:
    """One login's change in active days, with the baseline that produced it.

    `baseline_captured_at` rides beside the number because a delta with no as-of date is
    unfalsifiable: a reader cannot tell a month of change from a day of it.
    """

    login: str
    window_days: int
    active_days_now: int
    active_days_then: int
    delta: int
    baseline_captured_at: str
    history_days: float

    def to_dict(self) -> dict:
        return {
            "window": self.window_days,
            "active_days_now": self.active_days_now,
            "active_days_then": self.active_days_then,
            "delta": self.delta,
            "baseline_captured_at": self.baseline_captured_at,
            "history_days": self.history_days,
        }


def delta(store, login: str, window_days: int = DEFAULT_WINDOW_DAYS, *,
          min_history_days: int = MIN_HISTORY_DAYS, now=None):
    """`Delta` or `None`. NEVER a zero standing in for "no history".

    The baseline is the NEWEST snapshot at or before `now - min_history_days`: the
    freshest row that is still old enough to be a comparison rather than a restatement of
    today.
    """
    rows = list(store.active_day_snapshots(login, window_days) or [])
    if not rows:
        return None
    now_dt = _now(now)
    cutoff = now_dt - dt.timedelta(days=int(min_history_days))

    baseline = None
    for row in rows:                      # rows arrive oldest-first from the store
        when = _parse(row.get("captured_at"))
        if when is not None and when <= cutoff:
            baseline = (row, when)
    if baseline is None:
        return None

    latest = rows[-1]
    latest_at = _parse(latest.get("captured_at"))
    if latest_at is None:
        return None

    now_days = int(latest.get("active_days") or 0)
    then_days = int(baseline[0].get("active_days") or 0)
    return Delta(
        login=login,
        window_days=int(window_days),
        active_days_now=now_days,
        active_days_then=then_days,
        delta=now_days - then_days,
        baseline_captured_at=str(baseline[0].get("captured_at") or ""),
        history_days=round((latest_at - baseline[1]).total_seconds() / 86400.0, 2),
    )


def history_days(store, login: str, window_days: int = DEFAULT_WINDOW_DAYS) -> float:
    """How many days of history exist for this login/window. 0.0 when none do."""
    rows = list(store.active_day_snapshots(login, window_days) or [])
    if len(rows) < 2:
        return 0.0
    first = _parse(rows[0].get("captured_at"))
    last = _parse(rows[-1].get("captured_at"))
    if first is None or last is None:
        return 0.0
    return round((last - first).total_seconds() / 86400.0, 2)


def describe(store, login: str, window_days: int = DEFAULT_WINDOW_DAYS, *,
             min_history_days: int = MIN_HISTORY_DAYS, now=None) -> dict:
    """The artifact shape for one login: a delta, or `null` with a reason naming the days.

    `{"delta": null, "reason": "insufficient history: 3 of 7 days"}` says what is missing
    and when it will stop being missing. `{"delta": 0}` would say something false.
    """
    got = delta(store, login, window_days, min_history_days=min_history_days, now=now)
    if got is not None:
        return got.to_dict()
    have = history_days(store, login, window_days)
    return {
        "window": int(window_days),
        "delta": None,
        "reason": (f"insufficient history: {_days_label(have)} of "
                   f"{int(min_history_days)} days"),
    }


def report(store, logins, window_days: int = DEFAULT_WINDOW_DAYS, *,
           min_history_days: int = MIN_HISTORY_DAYS, now=None) -> dict:
    """`{login: describe(...)}` for every login given, in the order given.

    NOT SORTED, NOT RANKED, NOT FILTERED. A dict keyed by login, because the first thing
    a growth number invites is "show me who is growing fastest", which is a league table
    of humans by another name.
    """
    return {
        login: describe(store, login, window_days,
                        min_history_days=min_history_days, now=now)
        for login in logins
    }


def census_line(payload: dict, *, min_history_days: int = MIN_HISTORY_DAYS) -> str:
    """One honest sentence for the lane census. On day one it reads `0 of 2,568`."""
    total = len(payload)
    ready = sum(1 for entry in payload.values() if entry.get("delta") is not None)
    return (f"growth: {ready} of {total} logins have >={int(min_history_days)} days of "
            f"history (the rest report null with a reason, never 0)")


def _days_label(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _now(now):
    if now is None:
        return dt.datetime.now(dt.timezone.utc)
    if callable(now):
        return now()
    return now


def _parse(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
