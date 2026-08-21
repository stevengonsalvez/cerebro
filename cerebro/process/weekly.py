from __future__ import annotations

import datetime as _dt
from collections import Counter
from dataclasses import dataclass

from ..sink.vault_read import SignalNote

# Deterministic weekly selection. Pure: no IO, no clock, no LLM. Same notes in →
# byte-identical selection out, which is what makes the published roundup immutable
# and its feed item's guid/pubDate stable.

WeekKey = tuple[int, int]  # (ISO year, ISO week) — ISO year, NOT calendar year

#: Section order for `by_category`. Declared, never dict-insertion order, so the
#: rendered artifact does not depend on which category happened to score highest.
CATEGORY_ORDER = ("coding-agents-llm", "vibe-coding", "agentic-saas", "cli-tui")

TOP_N = 12
PER_SOURCE_CAP = 3
PER_CATEGORY_CAP = 5


def parse_week(text: str) -> WeekKey:
    """`"2026-w33"` → `(2026, 33)`."""
    raw = text.strip().lower()
    year, _, week = raw.partition("-w")
    if not week:
        raise ValueError(f"bad week {text!r}: expected e.g. 2026-w33")
    try:
        key = (int(year), int(week))
    except ValueError as exc:
        raise ValueError(f"bad week {text!r}: expected e.g. 2026-w33") from exc
    if not 1 <= key[1] <= 53:
        raise ValueError(f"bad week {text!r}: week must be 1..53")
    return key


def format_week(week: WeekKey) -> str:
    """`(2026, 3)` → `"2026-w03"` (`%G-w%V` semantics)."""
    return f"{week[0]:04d}-w{week[1]:02d}"


def iso_week_of(day: _dt.date) -> WeekKey:
    cal = day.isocalendar()
    return (cal[0], cal[1])


def week_bounds(week: WeekKey) -> tuple[_dt.date, _dt.date]:
    """Monday and Sunday of an ISO week."""
    start = _dt.date.fromisocalendar(week[0], week[1], 1)
    return start, start + _dt.timedelta(days=6)


def last_complete_week(today: _dt.date) -> WeekKey:
    """The most recent ISO week that has finished as of `today`.

    Takes the clock as an argument and never calls `date.today()`, so callers (and
    tests) pin it. Monday of this week minus one day is last week's Sunday.
    """
    monday = _dt.date.fromisocalendar(*iso_week_of(today), 1)
    return iso_week_of(monday - _dt.timedelta(days=1))


def sort_key(note: SignalNote) -> tuple[float, _dt.date, str]:
    """The total order: score desc, then capture date, then hash.

    Score alone is NOT an order — 206 corpus notes share 0.80 — so reruns would
    reshuffle. `hash` is the filename stem and therefore unique, which makes the
    order total and the selection reproducible.
    """
    return (-note.score, note.captured, note.hash)


@dataclass(frozen=True, slots=True)
class WeekSelection:
    week: WeekKey
    start: _dt.date
    end: _dt.date
    notes: tuple[SignalNote, ...]
    candidates: int
    relaxed: int
    #: (source, candidate count) over the WHOLE week, not just the selection —
    #: the render's "week in numbers" table needs the denominator.
    candidate_sources: tuple[tuple[str, int], ...]

    def by_category(self) -> tuple[tuple[str, tuple[SignalNote, ...]], ...]:
        """Selected notes grouped into sections, in CATEGORY_ORDER then alphabetical."""
        buckets: dict[str, list[SignalNote]] = {}
        for note in self.notes:
            buckets.setdefault(note.category, []).append(note)
        known = [c for c in CATEGORY_ORDER if c in buckets]
        unknown = sorted(c for c in buckets if c not in CATEGORY_ORDER)
        return tuple((c, tuple(buckets[c])) for c in known + unknown)


def select(
    notes,
    week: WeekKey,
    *,
    top_n: int = TOP_N,
    per_source_cap: int = PER_SOURCE_CAP,
    per_category_cap: int = PER_CATEGORY_CAP,
) -> WeekSelection:
    """Pick the week's roundup: highest-scoring notes, diversified by source/category.

    Two passes. The greedy pass enforces the caps so one loud source or one dominant
    category cannot own the issue. The relaxation pass then backfills, cap-free, in the
    same total order — otherwise a thin week (the corpus' first week has 18 candidates)
    would silently publish fewer than `top_n` items even though it had more to give.
    """
    start, end = week_bounds(week)
    candidates = sorted(
        (n for n in notes if iso_week_of(n.captured) == week), key=sort_key
    )

    picked: list[SignalNote] = []
    deferred: list[SignalNote] = []
    per_source: Counter[str] = Counter()
    per_category: Counter[str] = Counter()
    for note in candidates:
        if len(picked) >= top_n:
            break
        if per_source[note.source] >= per_source_cap or per_category[note.category] >= per_category_cap:
            deferred.append(note)
            continue
        picked.append(note)
        per_source[note.source] += 1
        per_category[note.category] += 1

    relaxed = 0
    if len(picked) < top_n:
        for note in deferred:
            if len(picked) >= top_n:
                break
            picked.append(note)
            relaxed += 1
        picked.sort(key=sort_key)

    return WeekSelection(
        week=week,
        start=start,
        end=end,
        notes=tuple(picked),
        candidates=len(candidates),
        relaxed=relaxed,
        candidate_sources=tuple(sorted(Counter(n.source for n in candidates).items())),
    )
