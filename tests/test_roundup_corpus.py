"""Roundup assertions against the REAL vault corpus.

Skipped wholesale when the corpus is absent — CI has no vault, and this suite must
never turn the pipeline red there. Everything here is read-only against the corpus;
nothing is written outside `tmp_path`.

The corpus grows by ~25 notes/day, so aggregates are asserted as invariants and
floors, or against the closed ISO weeks whose contents can no longer change.
"""
from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from cerebro.process import weekly
from cerebro.sink import roundup, vault_read

DEFAULT_CORPUS = Path(
    "/Users/stevengonsalvez/.agents-in-a-box/godmode/cerebro-vault-site/site/vault-cache"
)
CORPUS = Path(os.environ.get("CEREBRO_VAULT_CORPUS") or DEFAULT_CORPUS)

pytestmark = pytest.mark.skipif(
    not (CORPUS / "Signals").is_dir(), reason="vault corpus not present"
)

# Known scraped-body sentences. If any of these ever reaches a roundup, third-party
# article text is being republished — the one thing the read seam exists to prevent.
SENTINELS = (
    "整理关键数据",
    "Comparison of Models: Intelligence, Performance & Price Analysis",
    "Free, open source, backed by Markdown and HTML.",
)

# The first pipeline day. All of its notes predate the `reason` field, so a w25
# roundup is 100% empty-reason entries — the only real-data exercise of that branch.
FIRST_WEEK = (2026, 25)
# A closed, frozen week used for the exact-count assertions.
CLOSED_WEEK = (2026, 33)


@pytest.fixture(scope="module")
def corpus():
    return vault_read.read_signal_notes(CORPUS)


def test_every_corpus_note_parses(corpus):
    assert corpus.skipped == 0
    assert len(corpus.notes) >= 909              # floor: the vault only grows
    assert len({n.hash for n in corpus.notes}) == len(corpus.notes)


def _first_week(corpus):
    """The 18 notes of ISO week 2026-w25 — a CLOSED week, so this population is frozen.

    Exact counts are asserted here and never corpus-wide: the vault gains ~25 signals a
    day, and the pipeline omits the `reason:` key whenever triage reason is empty
    (`cerebro/sink/vault.py`), so a corpus-wide `== 18` would break the day a future
    note ships reason-less. Aggregates over the growing corpus are floors only.
    """
    return [n for n in corpus.notes if weekly.iso_week_of(n.captured) == FIRST_WEEK]


def test_the_first_day_notes_recover_their_titles_and_carry_an_empty_reason(corpus):
    first_week = _first_week(corpus)
    assert len(first_week) == 18                          # closed week: frozen count
    assert sum(1 for n in first_week if n.reason == "") == 18
    # Per-file fact about those same frozen notes: none of them has a `title` key, so
    # every one of them exercised the H1 recovery path.
    for note in first_week:
        fm, _ = vault_read._frontmatter((CORPUS / "Signals" / f"{note.hash}.md").read_text())
        assert not fm.get("title"), note.hash
    # Corpus-wide: floors and invariants only.
    assert corpus.title_recovered >= 18
    assert all(n.title for n in corpus.notes)
    assert [n for n in corpus.notes if n.reason is None] == []


def test_no_note_field_carries_a_scraped_body_sentence(corpus):
    for note in corpus.notes:
        blob = " ".join((note.title, note.category, note.source, note.url,
                         note.reason, *note.tags))
        for sentinel in SENTINELS:
            assert sentinel not in blob


def test_closed_week_selection_matches_its_measured_shape(corpus):
    sel = weekly.select(corpus.notes, CLOSED_WEEK)
    assert (sel.candidates, len(sel.notes), sel.relaxed) == (106, 12, 0)
    for src in {n.source for n in sel.notes}:
        assert sum(1 for n in sel.notes if n.source == src) <= 3
    for cat in {n.category for n in sel.notes}:
        assert sum(1 for n in sel.notes if n.category == cat) <= 5


def _weeks(notes):
    return sorted({weekly.iso_week_of(n.captured) for n in notes})


def test_every_week_fills_to_top_n_or_exhausts_its_candidates(corpus):
    for week in _weeks(corpus.notes):
        sel = weekly.select(corpus.notes, week)
        assert len(sel.notes) == min(weekly.TOP_N, sel.candidates), week


def test_every_week_renders_without_a_none_or_an_empty_blockquote(corpus):
    for week in _weeks(corpus.notes):
        text = roundup.render(weekly.select(corpus.notes, week))
        assert "None" not in text, week
        assert not [ln for ln in text.splitlines() if ln.strip() in (">", "> ")], week


def test_the_reasonless_first_week_still_renders_full_entries(corpus):
    sel = weekly.select(corpus.notes, FIRST_WEEK)
    assert (sel.candidates, len(sel.notes), sel.relaxed) == (18, 12, 6)
    assert all(n.reason == "" for n in sel.notes)
    text = roundup.render(sel)
    assert text.count("[[") == 12
    assert text.count("[Open ↗](") == 12
    assert "None" not in text


def test_render_is_byte_identical_across_reruns_and_input_orders(corpus):
    sel = weekly.select(corpus.notes, CLOSED_WEEK)
    baseline = roundup.render(sel)
    assert roundup.render(weekly.select(corpus.notes, CLOSED_WEEK)) == baseline
    shuffled = list(corpus.notes)
    random.Random(20260821).shuffle(shuffled)
    assert roundup.render(weekly.select(shuffled, CLOSED_WEEK)) == baseline


def test_the_rendered_roundup_contains_no_scraped_body_sentence(corpus):
    text = roundup.render(weekly.select(corpus.notes, CLOSED_WEEK))
    for sentinel in SENTINELS:
        assert sentinel not in text


def test_writing_the_roundup_touches_only_tmp_path(corpus, tmp_path):
    from types import SimpleNamespace

    # The corpus is allowed to CONTAIN a Weekly/ dir — since the roundup shipped, the
    # 07:00 run writes real ones into the vault, and a fetched cache mirrors them. The
    # invariant is that writing with vault_path=tmp_path leaves the corpus BYTE-FOR-BYTE
    # unchanged, so snapshot it rather than asserting a directory does not exist. The
    # old assertion encoded "the corpus has no Weekly/", which the feature made false.
    before = {p: p.stat().st_mtime_ns for p in CORPUS.rglob("*") if p.is_file()}

    sel = weekly.select(corpus.notes, CLOSED_WEEK)
    settings = SimpleNamespace(vault_path=tmp_path / "out", dry_run=False)
    result = roundup.write(sel, settings)
    assert result["written"] is True
    assert Path(result["path"]).is_relative_to(tmp_path)

    after = {p: p.stat().st_mtime_ns for p in CORPUS.rglob("*") if p.is_file()}
    assert after.keys() == before.keys(), (
        "writing the roundup must not add or remove any file in the read-only corpus: "
        f"added {sorted(after.keys() - before.keys())}, "
        f"removed {sorted(before.keys() - after.keys())}"
    )
    assert after == before, "writing the roundup must not modify any file in the corpus"
