"""Render + write + CLI contract for the weekly roundup, against a fixture vault built
by the REAL note writer (`cerebro.sink.vault._atomic`), so the read seam is exercised
against the exact bytes the pipeline produces."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cerebro import config, orchestrator
from cerebro.__main__ import main
from cerebro.models import Signal
from cerebro.process import weekly
from cerebro.sink import roundup, vault, vault_read

WEEK = (2026, 33)
WEEK_TEXT = "2026-w33"
SENTINEL = "Free, open source, backed by Markdown and HTML."

# Hand-written notes reproducing the three real corpus shapes `_atomic` cannot emit:
# a note with no `title` key (recoverable from its H1), a note with no `reason` key,
# and a note with an explicit `reason: null`.
NO_TITLE_HASH = "a" * 16
NO_REASON_KEY_HASH = "b" * 16
NULL_REASON_HASH = "c" * 16

_HAND_WRITTEN = {
    NO_TITLE_HASH: (
        "---\n"
        "category: coding-agents-llm\n"
        "tags: [ai/agents]\n"
        "source: github\n"
        "url: https://example.test/no-title\n"
        "score: 0.99\n"
        'reason: "recovered title note"\n'
        "captured: 2026-08-12T08:00:00+00:00\n"
        "rating:\n"
        "---\n"
        "# Title Recovered From The H1\n\n"
        f"{SENTINEL}\n"
    ),
    NO_REASON_KEY_HASH: (
        "---\n"
        'title: "No reason key at all"\n'
        "category: coding-agents-llm\n"
        "tags: [ai/agents]\n"
        "source: reddit\n"
        "url: https://example.test/no-reason\n"
        "score: 0.98\n"
        "captured: 2026-08-12T08:00:00+00:00\n"
        "rating:\n"
        "---\n"
        "# No reason key at all\n\nbody\n"
    ),
    NULL_REASON_HASH: (
        "---\n"
        'title: "Explicit null reason"\n'
        "category: coding-agents-llm\n"
        "tags: [ai/agents]\n"
        "source: rss\n"
        "url: https://example.test/null-reason\n"
        "score: 0.97\n"
        "reason: null\n"
        "captured: 2026-08-12T08:00:00+00:00\n"
        "rating:\n"
        "---\n"
        "# Explicit null reason\n\nbody\n"
    ),
}


@pytest.fixture
def fixture_vault(tmp_path: Path) -> Path:
    """30 signal notes in ISO week 2026-w33: 27 written by the real writer (one of them
    carrying a sentinel scraped-body sentence) plus the three hand-written shapes."""
    sig_dir = tmp_path / "vault" / "Signals"
    sig_dir.mkdir(parents=True)
    sources = ["github", "hackernews", "reddit", "rss"]
    categories = ["coding-agents-llm", "vibe-coding", "agentic-saas", "cli-tui"]
    for i in range(27):
        sig = Signal(
            url=f"https://example.test/{i}",
            title=f"Synthetic signal {i}",
            source=sources[i % len(sources)],
            category=categories[i % len(categories)],
            tags=["ai/agents"],
            score=0.90 - i / 100,
            captured=f"2026-08-{10 + i % 7:02d}T09:00:00+00:00",
            clean_text=(SENTINEL if i == 0 else f"body text {i}"),
            meta={"reason": f"why {i} matters"},
        )
        (sig_dir / f"{i:016x}.md").write_text(vault._atomic(sig))
    for hash_, text in _HAND_WRITTEN.items():
        (sig_dir / f"{hash_}.md").write_text(text)
    return tmp_path / "vault"


def _settings(vault_path: Path, dry_run: bool) -> SimpleNamespace:
    return SimpleNamespace(vault_path=vault_path, dry_run=dry_run)


def _select(fixture_vault: Path, week=WEEK, **kw):
    notes = vault_read.read_signal_notes(fixture_vault).notes
    return weekly.select(notes, week, **kw)


# ── read seam ────────────────────────────────────────────────────────────────

def test_read_seam_recovers_titles_and_never_yields_none_or_scraped_body(fixture_vault):
    result = vault_read.read_signal_notes(fixture_vault)
    assert len(result.notes) == 30
    assert result.skipped == 0
    assert result.title_recovered == 1

    by_hash = {n.hash: n for n in result.notes}
    assert by_hash[NO_TITLE_HASH].title == "Title Recovered From The H1"
    assert by_hash[NO_REASON_KEY_HASH].reason == ""
    assert by_hash[NULL_REASON_HASH].reason == ""
    assert all(n.reason is not None for n in result.notes)

    for note in result.notes:
        for value in (note.title, note.category, note.source, note.url, note.reason,
                      " ".join(note.tags)):
            assert SENTINEL not in value


def test_a_malformed_note_is_skipped_instead_of_killing_the_whole_read(fixture_vault):
    """Frontmatter is hand-editable YAML, so its value TYPES are not schema-guaranteed.
    A `tags:` scalar used to raise out of the read seam, and because run.sh soft-fails
    the roundup, that one note would have stopped weekly publication permanently and
    silently. Each malformed shape must cost exactly one note."""
    malformed = {
        "d" * 16: "tags: 42\n",                 # non-iterable scalar — the reported crash
        "e" * 16: "tags: {a: b}\n",             # mapping, iterates but is not a tag list
        "f" * 16: "tags: [ai/agents]\nscore: .nan\n",   # unorderable score
        "0abcdef012345678": "tags: [ai/agents]\nscore: .inf\n",
    }
    for hash_, extra in malformed.items():
        (fixture_vault / "Signals" / f"{hash_}.md").write_text(
            "---\n"
            f'title: "malformed {hash_}"\n'
            "category: cli-tui\n"
            "source: rss\n"
            "url: https://example.test/malformed\n"
            "score: 0.5\n"
            "captured: 2026-08-12T08:00:00+00:00\n"
            f"{extra}"
            "---\n"
            "# malformed\n\nbody\n"
        )
    result = vault_read.read_signal_notes(fixture_vault)
    assert result.skipped == len(malformed)
    assert len(result.notes) == 30                       # every healthy note survives
    assert not ({h for h in malformed} & {n.hash for n in result.notes})
    assert all(isinstance(n.tags, tuple) for n in result.notes)


def test_a_non_finite_score_can_never_reach_selection(fixture_vault):
    """NaN compares false against everything, so a single NaN score turns
    `weekly.sort_key`'s claimed total order into an input-order-dependent one. Two
    NaN notes in opposite input orders must still select the same roundup."""
    for hash_ in ("1" * 16, "2" * 16):
        (fixture_vault / "Signals" / f"{hash_}.md").write_text(
            "---\n"
            f'title: "nan {hash_}"\n'
            "category: cli-tui\n"
            "tags: [ai/agents]\n"
            "source: rss\n"
            "url: https://example.test/nan\n"
            "score: .nan\n"
            "captured: 2026-08-12T08:00:00+00:00\n"
            "---\n"
            "# nan\n\nbody\n"
        )
    notes = vault_read.read_signal_notes(fixture_vault).notes
    assert all(n.score == n.score for n in notes)
    forward = [n.hash for n in weekly.select(notes, WEEK).notes]
    backward = [n.hash for n in weekly.select(list(reversed(notes)), WEEK).notes]
    assert forward == backward


# ── render ───────────────────────────────────────────────────────────────────

def test_render_omits_the_blockquote_line_but_keeps_reasonless_entries(fixture_vault):
    sel = _select(fixture_vault, per_source_cap=99, per_category_cap=99)
    picked = {n.hash for n in sel.notes}
    assert {NO_REASON_KEY_HASH, NULL_REASON_HASH} <= picked

    text = roundup.render(sel)
    assert "None" not in text
    assert not [ln for ln in text.splitlines() if ln.strip() in (">", "> ")]
    for hash_ in (NO_REASON_KEY_HASH, NULL_REASON_HASH):
        assert f"[[{hash_}|" in text
    # the entries survive, only their reason line is gone
    assert text.count("[Open ↗](") == len(sel.notes)


def test_render_is_byte_stable_and_carries_no_clock_value(fixture_vault):
    sel = _select(fixture_vault)
    first = roundup.render(sel)
    assert first == roundup.render(sel)
    frontmatter = first.split("---\n")[1]
    assert not re.search(r"^(generated|timestamp|run_id|now|created)\s*:", frontmatter, re.M)
    assert set(yaml.safe_load(frontmatter)) == {
        "type", "week", "start", "end", "title", "count", "candidates",
        "sources", "categories",
    }


def test_rendered_frontmatter_and_body_describe_the_selection(fixture_vault):
    sel = _select(fixture_vault)
    text = roundup.render(sel)
    fm = yaml.safe_load(text.split("---\n")[1])
    assert fm["type"] == "cerebro-weekly"
    assert fm["week"] == WEEK_TEXT
    # YAML round-trips the bare ISO dates back into `date` objects
    assert (fm["start"], fm["end"]) == (dt.date(2026, 8, 10), dt.date(2026, 8, 16))
    assert "start: 2026-08-10\nend: 2026-08-16\n" in text
    assert fm["count"] == len(sel.notes)
    assert fm["candidates"] == sel.candidates
    assert fm["title"].startswith("CEREBRO Weekly")
    for note in sel.notes:
        assert f"[[{note.hash}|" in text
        assert note.title in text


# ── write ────────────────────────────────────────────────────────────────────

def test_write_routes_dry_runs_to_scratch(fixture_vault):
    sel = _select(fixture_vault)
    result = roundup.write(sel, _settings(fixture_vault, dry_run=True))
    assert result["written"] is True
    assert Path(result["path"]) == fixture_vault / "_scratch" / "Weekly" / f"{WEEK_TEXT}.md"
    assert Path(result["path"]).is_file()
    assert not (fixture_vault / "Weekly" / f"{WEEK_TEXT}.md").exists()


def test_write_routes_real_runs_to_the_vault(fixture_vault):
    sel = _select(fixture_vault)
    result = roundup.write(sel, _settings(fixture_vault, dry_run=False))
    assert Path(result["path"]) == fixture_vault / "Weekly" / f"{WEEK_TEXT}.md"
    assert Path(result["path"]).is_file()
    assert result["count"] == len(sel.notes)
    assert result["candidates"] == sel.candidates
    assert result["week"] == WEEK_TEXT


def test_write_is_write_once_unless_forced(fixture_vault):
    sel = _select(fixture_vault)
    settings = _settings(fixture_vault, dry_run=False)
    first = roundup.write(sel, settings)
    target = Path(first["path"])
    target.write_text("hand-edited")

    second = roundup.write(sel, settings)
    assert second["written"] is False
    assert second["reason"] == "exists"
    assert target.read_text() == "hand-edited"

    third = roundup.write(sel, settings, force=True)
    assert third["written"] is True
    assert target.read_text() == roundup.render(sel)


def test_a_crash_mid_write_leaves_no_stump_and_the_next_run_heals(fixture_vault,
                                                                   monkeypatch):
    """Write-once + non-atomic is the dangerous pair: a truncated file satisfies the
    exists-check, so the next run reports `exists` and refuses to heal it while run.sh
    stages `Weekly/` and pushes it to the PUBLIC vault. `os.replace` means the target
    only ever appears complete."""
    sel = _select(fixture_vault)
    settings = _settings(fixture_vault, dry_run=False)
    target = fixture_vault / "Weekly" / f"{WEEK_TEXT}.md"

    real_write_text = Path.write_text

    def killed_mid_flush(self, text, *args, **kwargs):
        real_write_text(self, text[: len(text) // 2])
        raise KeyboardInterrupt("killed mid-write")

    monkeypatch.setattr(Path, "write_text", killed_mid_flush)
    with pytest.raises(KeyboardInterrupt):
        roundup.write(sel, settings)
    monkeypatch.undo()

    assert not target.exists()                       # no partial roundup to publish
    assert list((fixture_vault / "Weekly").iterdir()) == []   # and no temp file either

    healed = roundup.write(sel, settings)
    assert (healed["written"], healed["reason"]) == (True, "written")
    assert target.read_text() == roundup.render(sel)


def test_a_stale_temp_file_is_swept_so_it_can_never_be_pushed(fixture_vault):
    """run.sh stages the whole `Weekly/` directory, so a temp file left by a power loss
    would be committed to the public vault on the next run."""
    sel = _select(fixture_vault)
    weekly_dir = fixture_vault / "Weekly"
    weekly_dir.mkdir(parents=True)
    (weekly_dir / ".2026-w20.md.tmp").write_text("half a roundup")

    roundup.write(sel, _settings(fixture_vault, dry_run=False))
    assert [p.name for p in weekly_dir.iterdir()] == [f"{WEEK_TEXT}.md"]


def test_write_refuses_an_empty_week(fixture_vault):
    sel = _select(fixture_vault, week=(2026, 20))
    result = roundup.write(sel, _settings(fixture_vault, dry_run=False))
    assert result == {
        "week": "2026-w20", "path": result["path"], "count": 0, "candidates": 0,
        "relaxed": 0, "written": False, "reason": "no-signals",
    }
    assert not (fixture_vault / "Weekly").exists()


# ── CLI ──────────────────────────────────────────────────────────────────────

class _RecordingLoad:
    """Stands in for `cerebro.config.load`, recording the tri-state override and
    mimicking `settings.example.yaml`'s `dry_run: true` when the override is None."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.override = "unset"

    def __call__(self, dry_run_override=None, allow_example=False):
        self.override = dry_run_override
        dry = True if dry_run_override is None else dry_run_override
        return SimpleNamespace(vault_path=self.vault_path, dry_run=dry)


@pytest.fixture
def cli(monkeypatch, fixture_vault):
    loader = _RecordingLoad(fixture_vault)
    monkeypatch.setattr(config, "load", loader)
    monkeypatch.setattr(orchestrator, "run", _never_reached)
    return loader


def _never_reached(*a, **k):
    raise AssertionError("roundup must return before the orchestrator is reached")


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["cerebro", "roundup", *argv])
    main()
    return json.loads(capsys.readouterr().out)


def test_cli_dry_run_flag_forces_the_scratch_root(cli, monkeypatch, capsys, fixture_vault):
    out = _run(monkeypatch, capsys, ["--week", WEEK_TEXT, "--dry-run"])
    assert cli.override is True
    assert out["dry_run"] is True
    assert Path(out["path"]) == fixture_vault / "_scratch" / "Weekly" / f"{WEEK_TEXT}.md"
    assert out["written"] is True


def test_cli_write_flag_forces_the_real_root(cli, monkeypatch, capsys, fixture_vault):
    out = _run(monkeypatch, capsys, ["--week", WEEK_TEXT, "--write"])
    assert cli.override is False              # not None — the whole point of the tri-state
    assert out["dry_run"] is False
    target = fixture_vault / "Weekly" / f"{WEEK_TEXT}.md"
    assert Path(out["path"]) == target
    assert "_scratch" not in out["path"]
    assert target.is_file()


def test_cli_without_a_flag_defers_to_settings(cli, monkeypatch, capsys, fixture_vault):
    out = _run(monkeypatch, capsys, ["--week", WEEK_TEXT])
    assert cli.override is None               # must NOT be coerced to a bool
    assert out["dry_run"] is True             # ...so the loaded settings decide
    assert Path(out["path"]) == fixture_vault / "_scratch" / "Weekly" / f"{WEEK_TEXT}.md"


def test_cli_rejects_both_flags_together(cli, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cerebro", "roundup", "--dry-run", "--write"])
    with pytest.raises(SystemExit):
        main()


def test_cli_reports_an_existing_note_without_failing(cli, monkeypatch, capsys):
    _run(monkeypatch, capsys, ["--week", WEEK_TEXT, "--write"])
    out = _run(monkeypatch, capsys, ["--week", WEEK_TEXT, "--write"])
    assert out["written"] is False
    assert out["reason"] == "exists"


def test_cli_honours_the_cap_flags(cli, monkeypatch, capsys):
    out = _run(monkeypatch, capsys,
               ["--week", WEEK_TEXT, "--write", "--top-n", "4", "--per-source-cap", "1"])
    assert out["count"] == 4
