from __future__ import annotations

import datetime as _dt
import os

from ..process.weekly import WeekSelection, format_week
from .vault import _alias, _yaml_list, _yaml_value

# Weekly roundup note: render + write.
#
# `render` is a pure function of the selection — no clock, no run id, no disk. That is
# deliberate and load-bearing: any timestamp in the artifact makes a rerun produce
# different bytes, which churns the feed item's guid/pubDate downstream and makes the
# determinism guarantee unprovable. The week's `end` date is the only "time" the
# artifact carries, and it is derived from the ISO week, not from the clock.

#: Section headings, matching the labels the daily briefings already use. Unknown
#: categories fall back to their raw key rather than being dropped.
CATEGORY_LABELS = {
    "coding-agents-llm": "Coding agents & LLM mechanics",
    "vibe-coding": "Vibe-coding & agent infra",
    "agentic-saas": "Agentic SaaS",
    "cli-tui": "CLI/TUI",
}

#: Month names as literals, never `%b` — `strftime` is locale-dependent and a
#: locale change would silently break byte-identical reruns.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month(day: _dt.date) -> str:
    return _MONTHS[day.month - 1]


def _span(start: _dt.date, end: _dt.date) -> str:
    """Human date span for the title, e.g. `10–16 Aug 2026`. Deterministic, locale-free."""
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {_month(start)} {start.year}"
    if start.year == end.year:
        return f"{start.day} {_month(start)} – {end.day} {_month(end)} {end.year}"
    return f"{start.day} {_month(start)} {start.year} – {end.day} {_month(end)} {end.year}"


def title_of(sel: WeekSelection) -> str:
    return f"CEREBRO Weekly — {_span(sel.start, sel.end)}"


def _entry(note) -> str:
    """One roundup entry.

    The wikilink is the daily briefing's existing `[[hash|title]]` form, so the site's
    existing parser resolves it to the signal archive with no new site-side work.
    `_alias` is imported from the daily writer rather than re-implemented so wikilink
    escaping cannot drift between the daily and the weekly.

    Only whitelisted fields appear here (title, hash, source, score, reason, url) —
    `SignalNote` carries nothing else, so the no-scraped-body property is inherited
    from the read seam rather than re-asserted here.
    """
    lines = [f"- [[{note.hash}|{_alias(note.title)}]] · {note.source} · {note.score:.2f}"]
    if note.reason:
        # Mirrors the daily writer's `rquote`: no reason → no blockquote line at all.
        # The pipeline's first week has 18 candidates and ALL of them are reason-less,
        # so this branch is the normal case for that week, not a cosmetic edge case.
        lines.append(f"  > {note.reason}")
    lines.append(f"  [Open ↗]({note.url})")
    return "\n".join(lines)


def _numbers(sel: WeekSelection) -> str:
    """Provenance table: what each source contributed, against what it offered."""
    in_roundup: dict[str, int] = {}
    for note in sel.notes:
        in_roundup[note.source] = in_roundup.get(note.source, 0) + 1
    candidates = dict(sel.candidate_sources)
    rows = sorted(
        set(candidates) | set(in_roundup),
        key=lambda k: (-in_roundup.get(k, 0), -candidates.get(k, 0), k),
    )
    body = "\n".join(
        f"| {k} | {in_roundup.get(k, 0)} | {candidates.get(k, 0)} |" for k in rows
    )
    return (
        "## The week in numbers\n\n"
        "| source | in roundup | candidates |\n|---|--:|--:|\n"
        f"{body}\n| **total** | **{len(sel.notes)}** | **{sel.candidates}** |\n"
    )


def render(sel: WeekSelection) -> str:
    """The weekly note, as a string. Pure — identical selection ⇒ identical bytes."""
    title = title_of(sel)
    sources = sorted({n.source for n in sel.notes})
    categories = sorted({n.category for n in sel.notes if n.category})
    sections = []
    for category, notes in sel.by_category():
        heading = CATEGORY_LABELS.get(category, category or "Uncategorised")
        entries = "\n\n".join(_entry(n) for n in notes)
        sections.append(f"## {heading}\n\n{entries}\n")
    return (
        "---\n"
        "type: cerebro-weekly\n"
        f"week: {format_week(sel.week)}\n"
        f"start: {sel.start.isoformat()}\n"
        f"end: {sel.end.isoformat()}\n"
        f"title: {_yaml_value(title)}\n"
        f"count: {len(sel.notes)}\n"
        f"candidates: {sel.candidates}\n"
        f"sources: {_yaml_list(sources)}\n"
        f"categories: {_yaml_list(categories)}\n"
        "---\n"
        f"# {title}\n\n"
        f"{len(sel.notes)} of {sel.candidates} signals from "
        f"{sel.start.isoformat()} to {sel.end.isoformat()}.\n\n"
        + "\n".join(sections)
        + "\n"
        + _numbers(sel)
    )


def write(sel: WeekSelection, settings, *, force: bool = False) -> dict:
    """Write `Weekly/<isoyear>-w<ww>.md`. Dry-run → `_scratch/Weekly/`.

    Write-once by default. A published roundup is immutable: re-generating it after a
    signal was re-captured into a later week would silently reshuffle an issue readers
    (and the feed) have already seen. `force` is the explicit opt-out.
    """
    root = (settings.vault_path / "_scratch") if settings.dry_run else settings.vault_path
    target = root / "Weekly" / f"{format_week(sel.week)}.md"
    result = {
        "week": format_week(sel.week),
        "path": str(target),
        "count": len(sel.notes),
        "candidates": sel.candidates,
        "relaxed": sel.relaxed,
        "written": False,
        "reason": "",
    }
    if not sel.notes:
        result["reason"] = "no-signals"
        return result
    if target.exists() and not force:
        result["reason"] = "exists"
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, render(sel))
    result["written"] = True
    result["reason"] = "written"
    return result


def _atomic_write(target, text: str) -> None:
    """Write `text` to `target` atomically: full temp file, then `os.replace`.

    Write-once and non-atomic are a bad pair. A plain `write_text` that is killed
    mid-flush leaves a TRUNCATED roundup on disk; the exists-check above then reads that
    stump as "already published" and refuses to heal it on every subsequent run, while
    run.sh stages `Weekly/` and pushes it to the PUBLIC vault. `os.replace` is atomic on
    POSIX, so the exists-check can only ever observe a complete file.

    The temp file is dot-prefixed and lives in the target directory (same filesystem —
    a cross-device rename is not atomic). It is removed in `finally`, and any stump left
    by a power loss is swept on the next write, because run.sh's `git add -- Weekly`
    would otherwise publish it.
    """
    for stale in target.parent.glob(".*.md.tmp"):
        try:
            stale.unlink()
        except OSError:
            pass
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
