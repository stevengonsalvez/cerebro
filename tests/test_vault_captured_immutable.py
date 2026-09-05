"""`captured` is a claim about the past, so a rewrite must not restate it.

THE BUG THIS PINS, measured on the live vault rather than imagined: every source stamps
`captured=now_iso()` at fetch, and `vault.write` rewrites the whole note whenever a signal is
re-admitted. Between 2026-08-21 and 2026-09-05, 26 notes had `captured` rewritten to a later
day and ALL 26 changed ISO week. `weekly.select` attributes a note to a week with
`iso_week_of(n.captured)`, so a CLOSED week silently changed composition after publication —
five notes left week 2026-w33, and an already-published roundup and the archive stopped
agreeing about which week those signals belonged to.
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

from cerebro.models import Signal
from cerebro.sink import vault


def _settings(tmp_path: pathlib.Path) -> SimpleNamespace:
    return SimpleNamespace(vault_path=tmp_path, dry_run=False)


def _signal(captured: str, *, title: str = "A post", score: float = 0.8) -> Signal:
    return Signal(
        url="https://example.com/a",
        title=title,
        source="hackernews",
        captured=captured,
        score=score,
        category="coding-agents-llm",
    )


def _write(tmp_path, sig):
    vault.write("2026-09-05", "briefing", [sig], _settings(tmp_path), None)
    return (tmp_path / "Signals" / f"{sig.url_hash}.md").read_text(encoding="utf-8")


def test_a_re_admitted_signal_keeps_the_day_it_was_first_written(tmp_path):
    first = _signal("2026-08-15T06:00:05.480092+00:00")
    _write(tmp_path, first)
    # Same URL, so the same note, coming back a fortnight later with a fresh fetch stamp.
    again = _signal("2026-08-30T06:00:05.018014+00:00", title="A post, retitled", score=0.91)
    text = _write(tmp_path, again)

    assert "captured: 2026-08-15T06:00:05.480092+00:00" in text
    assert "2026-08-30" not in text


def test_everything_else_on_the_note_is_still_refreshed(tmp_path):
    _write(tmp_path, _signal("2026-08-15T06:00:05.480092+00:00"))
    text = _write(tmp_path, _signal("2026-08-30T06:00:05.018014+00:00", title="A post, retitled", score=0.91))

    # Only the one field is a claim about the past; a re-admitted signal is otherwise current.
    assert "A post, retitled" in text
    assert "score: 0.91" in text


def test_the_week_a_note_belongs_to_no_longer_moves(tmp_path):
    # The property the roundup actually depends on, asserted as the roundup asserts it.
    import datetime as dt

    from cerebro.process.weekly import iso_week_of

    _write(tmp_path, _signal("2026-08-15T06:00:05.480092+00:00"))
    text = _write(tmp_path, _signal("2026-08-30T06:00:05.018014+00:00"))
    captured = next(l.split(": ", 1)[1] for l in text.splitlines() if l.startswith("captured: "))
    # Attributed to w33 where it was captured, not w35 where it came back. Without the
    # guard this is (2026, 35) and a closed week has quietly changed.
    assert iso_week_of(dt.datetime.fromisoformat(captured).date()) == (2026, 33)


def test_a_first_write_still_records_the_fetch_stamp(tmp_path):
    # The guard reads an EXISTING note. With none, nothing is preserved and the fetch stamp
    # is the first-seen day, which is the whole point of it.
    text = _write(tmp_path, _signal("2026-09-05T06:00:08.092801+00:00"))
    assert "captured: 2026-09-05T06:00:08.092801+00:00" in text


def test_a_rated_note_is_still_never_touched(tmp_path):
    first = _signal("2026-08-15T06:00:05.480092+00:00")
    _write(tmp_path, first)
    p = tmp_path / "Signals" / f"{first.url_hash}.md"
    p.write_text(p.read_text(encoding="utf-8").replace("rating:\n", "rating: 5\n"), encoding="utf-8")

    _write(tmp_path, _signal("2026-08-30T06:00:05.018014+00:00", title="A post, retitled"))
    after = p.read_text(encoding="utf-8")
    assert "rating: 5" in after
    assert "A post, retitled" not in after
