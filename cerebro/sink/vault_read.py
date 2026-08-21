from __future__ import annotations

import datetime as _dt
import pathlib
from dataclasses import dataclass
from typing import NamedTuple

import yaml

# Read seam for the vault's Signals/ notes.
#
# Every signal note embeds the full trafilatura-scraped source body. That body must
# never leave this module: republishing third-party article text is a legal/SEO
# constraint, not a preference. So this module parses the YAML frontmatter ONLY and
# projects it onto a frozen dataclass whose fields are exactly WHITELIST. Anything
# downstream (selection, render, the site) can therefore only ever see whitelisted
# metadata — the safety property is structural, not a review habit.

#: The only frontmatter keys any consumer of a signal note may see. `hash` is not
#: here because it is the filename stem, not a frontmatter key.
WHITELIST = ("title", "category", "tags", "source", "url", "score", "reason", "captured")


@dataclass(frozen=True, slots=True)
class SignalNote:
    """One signal note, reduced to its publishable metadata.

    Domain-typed rather than primitive-typed: `captured` is a `date` (YAML hands back
    a `datetime`; it is normalised once, here), `score` a `float`, `tags` an immutable
    tuple. No field is ever `None` — absent strings collapse to `""` — so no renderer
    downstream has to defend against a literal `None` leaking into the artifact.
    """

    hash: str
    title: str
    category: str
    tags: tuple[str, ...]
    source: str
    url: str
    score: float
    reason: str
    captured: _dt.date


class ReadResult(NamedTuple):
    """`read_signal_notes` result: the notes plus the counters that prove the read.

    `skipped` counts notes without a usable `captured`/`score` (they cannot be placed
    in a week or ordered); `title_recovered` counts notes whose `title` key was absent
    and was recovered from the note's own H1.
    """

    notes: list[SignalNote]
    skipped: int
    title_recovered: int


def _frontmatter(text: str) -> tuple[dict, int] | None:
    """Parse the leading `---` YAML block. Returns (mapping, body_offset) or None.

    Same shape as the proven `cerebro/process/feedback.py:_frontmatter` helper.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None
    return data, end + len("\n---")


def _recover_title(body: str) -> str:
    """Recover a missing `title` from the note's own H1 — and nothing else.

    18 of the corpus notes (the pipeline's first day) have no `title` frontmatter key.
    Their first body line is the `# {title}` heading written by
    `cerebro/sink/vault.py` from the signal's own title, so it is provably the
    signal title and not scraped prose. Reading that ONE line, gated on the `# `
    prefix, is the ONLY body access in this module: anything after it is the
    third-party article body and must never be read.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            return " ".join(stripped[2:].split())
        return ""      # first non-empty line is not an H1 → do not read further
    return ""


def _as_date(value) -> _dt.date | None:
    """Normalise a `captured` value to a `date`. YAML auto-types ISO8601 to datetime."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _one_line(value) -> str:
    """Collapse a possibly-missing, possibly-None, possibly-multiline scalar to one line."""
    return " ".join(str(value or "").split())


def _note(hash_: str, fm: dict, body: str) -> tuple[SignalNote, bool] | None:
    """Project a frontmatter mapping onto a SignalNote. Returns (note, title_recovered)."""
    captured = _as_date(fm.get("captured"))
    if captured is None:
        return None
    try:
        score = float(fm.get("score"))
    except (TypeError, ValueError):
        return None

    title = _one_line(fm.get("title"))
    recovered = False
    if not title:
        title = _recover_title(body)
        recovered = bool(title)

    raw_tags = fm.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    tags = tuple(_one_line(t) for t in raw_tags if _one_line(t))

    return (
        SignalNote(
            hash=hash_,
            title=title,
            category=_one_line(fm.get("category")),
            tags=tags,
            source=_one_line(fm.get("source")),
            url=_one_line(fm.get("url")),
            score=score,
            # `reason` is absent or explicitly null on the pipeline's first-day notes,
            # and those notes are the whole of ISO week 25 — without this normalisation a
            # w25 roundup renders `> None` for every entry. Single-lined here so the
            # renderer never re-cleans it, and typed `str` so `""` is the empty case.
            reason=_one_line(fm.get("reason")),
            captured=captured,
        ),
        recovered,
    )


def read_signal_notes(vault_path) -> ReadResult:
    """Read every `Signals/*.md` note under `vault_path` into whitelisted SignalNotes.

    Sorted by `hash` so the base order is independent of filesystem glob order — the
    first of the two guarantees that make weekly selection reproducible.
    """
    sig_dir = pathlib.Path(vault_path) / "Signals"
    notes: list[SignalNote] = []
    skipped = 0
    recovered_count = 0
    if not sig_dir.is_dir():
        return ReadResult([], 0, 0)
    for path in sorted(sig_dir.glob("*.md")):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            skipped += 1
            continue
        parsed = _frontmatter(text)
        if parsed is None:
            skipped += 1
            continue
        fm, body_offset = parsed
        built = _note(path.stem, fm, text[body_offset:])
        if built is None:
            skipped += 1
            continue
        note, recovered = built
        notes.append(note)
        recovered_count += int(recovered)
    notes.sort(key=lambda n: n.hash)
    return ReadResult(notes, skipped, recovered_count)
