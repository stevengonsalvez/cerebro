"""Pure selection + week-maths tests. No IO, no corpus — these run in CI."""
from __future__ import annotations

import datetime as dt
import random

import pytest

from cerebro.process import weekly
from cerebro.sink import vault_read
from cerebro.sink.vault_read import SignalNote


def _note(hash_: str, *, score: float, source: str = "rss", category: str = "cli-tui",
          captured: dt.date = dt.date(2026, 8, 12), reason: str = "why") -> SignalNote:
    return SignalNote(
        hash=hash_, title=f"title {hash_}", category=category, tags=("t",),
        source=source, url=f"https://example.test/{hash_}", score=score,
        reason=reason, captured=captured,
    )


def test_signalnote_fields_are_exactly_the_whitelist():
    """A new field on SignalNote is a new field the site could render. Adding one
    without extending the render whitelist must fail the build, not pass review."""
    assert set(SignalNote.__dataclass_fields__) - {"hash"} == set(vault_read.WHITELIST)


def test_caps_bound_each_source_and_category():
    notes = [
        _note(f"{i:016x}", score=1.0 - i / 100,
              source=f"src{i % 3}", category=f"cat{i % 3}")
        for i in range(60)
    ]
    sel = weekly.select(notes, (2026, 33), top_n=6, per_source_cap=2, per_category_cap=3)
    assert len(sel.notes) == 6
    for src in {n.source for n in sel.notes}:
        assert sum(1 for n in sel.notes if n.source == src) <= 2
    for cat in {n.category for n in sel.notes}:
        assert sum(1 for n in sel.notes if n.category == cat) <= 3


def test_selection_is_independent_of_input_order():
    notes = [
        _note(f"{i:016x}", score=round(0.5 + (i % 5) / 10, 2), source=f"src{i % 4}",
              category=f"cat{i % 3}", captured=dt.date(2026, 8, 10 + i % 7))
        for i in range(40)
    ]
    shuffled = notes[:]
    random.Random(1234).shuffle(shuffled)
    assert [n.hash for n in weekly.select(notes, (2026, 33)).notes] == \
           [n.hash for n in weekly.select(shuffled, (2026, 33)).notes]


def test_equal_score_and_date_break_on_hash():
    low, high = _note("0" * 16, score=0.8), _note("f" * 16, score=0.8)
    sel = weekly.select([high, low], (2026, 33), top_n=2)
    assert [n.hash for n in sel.notes] == ["0" * 16, "f" * 16]


def test_relaxation_backfills_a_starved_week():
    notes = [_note(f"{i:016x}", score=0.9 - i / 100, source="rss") for i in range(5)]
    sel = weekly.select(notes, (2026, 33), top_n=4, per_source_cap=2, per_category_cap=99)
    assert len(sel.notes) == 4
    assert sel.relaxed == 2
    assert sel.candidates == 5


def test_empty_week_selects_nothing():
    sel = weekly.select([_note("a" * 16, score=0.9)], (2026, 30))
    assert sel.notes == ()
    assert sel.candidates == 0
    assert sel.relaxed == 0


@pytest.mark.parametrize("moment,expected", [
    (dt.date(2026, 8, 16), (2026, 33)),      # Sunday 23:59 is still w33
    (dt.date(2026, 8, 17), (2026, 34)),      # Monday 00:00 flips to w34
    (dt.date(2027, 1, 1), (2026, 53)),       # ISO year, not calendar year
])
def test_iso_week_boundaries(moment, expected):
    assert weekly.iso_week_of(moment) == expected


def test_last_complete_week_takes_the_clock_as_an_argument():
    assert weekly.last_complete_week(dt.date(2026, 8, 21)) == (2026, 33)
    assert weekly.last_complete_week(dt.date(2026, 8, 17)) == (2026, 33)
    assert weekly.last_complete_week(dt.date(2026, 8, 16)) == (2026, 32)


def test_week_format_round_trip():
    assert weekly.format_week((2026, 3)) == "2026-w03"
    for key in ((2026, 1), (2026, 33), (2026, 53)):
        assert weekly.parse_week(weekly.format_week(key)) == key


def test_week_bounds_are_monday_to_sunday():
    start, end = weekly.week_bounds((2026, 33))
    assert (start, end) == (dt.date(2026, 8, 10), dt.date(2026, 8, 16))
    assert start.isoweekday() == 1 and end.isoweekday() == 7


def test_parse_week_rejects_rubbish():
    for bad in ("2026", "2026-33", "2026-w99", "wat"):
        with pytest.raises(ValueError):
            weekly.parse_week(bad)


def test_by_category_uses_a_declared_order_not_insertion_order():
    notes = [
        _note("a" * 16, score=0.9, category="agentic-saas"),
        _note("b" * 16, score=0.8, category="coding-agents-llm"),
        _note("c" * 16, score=0.7, category="zzz-unknown"),
        _note("d" * 16, score=0.6, category="cli-tui"),
    ]
    sel = weekly.select(notes, (2026, 33))
    assert [c for c, _ in sel.by_category()] == [
        "coding-agents-llm", "agentic-saas", "cli-tui", "zzz-unknown",
    ]
