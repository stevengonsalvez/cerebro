"""F071 — the gate on what the digest model actually returned.

Every fixture below is text that REACHED READERS on stevengonsalvez.com between
2026-08-18 and 2026-09-05, copied from the published briefings rather than invented.
"""
from __future__ import annotations

import pytest

from cerebro.process import briefing_gate as gate

# Verbatim from vault/Daily/2026-09-04.md as published.
REAL_LEAK = """# CEREBRO — 2026-09-04

File written: vault/Daily/2026-09-04.md, 25/25 signals, 4 theme groups, GPT-6 Astra launch leads.

| thread | state | next |
|---|---|---|
| daily briefing 2026-09-04 | written, untracked in vault submodule | commit in vault |

next: commit vault/Daily/2026-09-04.md via /commit
- vault is submodule, shows as "modified: vault (new commits)" at parent repo level [fact]
- no pipeline token/cost stats available (manual write, not automated digest run) [fact]

## Signals
- [[82a901da1b9bedec|anthropics/skills: Public repository for Agent Skills]] · github · 0.95
- [[6379e22bcefbb3cd|Which tools do Claude, Codex and Cursor choose?]] · hackernews · 0.90
"""

# Verbatim from vault/Daily/2026-09-05.md as published.
REAL_ASK = """# CEREBRO — 2026-09-05

AskUserQuestion tool not in this session, plaintext fallback per skill.

### Question: push vault commit `9080b1b` ("vault: 2026-09-05 daily briefing") to origin/main?
1. **Yes, push now** (Recommended, matches every prior day's commit pattern)
2. No, leave local only

## Signals
- [[bac657e60ae022eb|JuliusBrussee/caveman]] · github · 0.90
"""


def test_the_published_leak_is_detected():
    found = gate.scan(REAL_LEAK)
    assert found, "this exact text was on the live site for a day"
    assert found["turn_end_table"] == 1
    assert found["fact_bullet"] == 2
    assert found["next_line"] == 1
    assert found["self_status"] == 1


def test_the_published_question_preamble_is_detected():
    found = gate.scan(REAL_ASK)
    assert found["askuserquestion"] == 1
    assert found["numbered_question"] == 1


@pytest.mark.parametrize("sample", [REAL_LEAK, REAL_ASK])
def test_sanitize_removes_every_artefact_and_leaves_nothing_behind(sample):
    clean, found = gate.sanitize(sample)
    assert found
    assert gate.scan(clean) == {}, "a partial strip is worse than none: it looks fixed"


@pytest.mark.parametrize("sample", [REAL_LEAK, REAL_ASK])
def test_every_signal_survives(sample):
    """The signals were always correct. Only the commentary was wrong."""
    before = [l for l in sample.splitlines() if l.startswith("- [[")]
    clean, _ = gate.sanitize(sample)
    after = [l for l in clean.splitlines() if l.startswith("- [[")]
    assert before == after and before, "stripping must never cost a signal"


def test_the_heading_survives():
    clean, _ = gate.sanitize(REAL_LEAK)
    assert "# CEREBRO — 2026-09-04" in clean
    assert "## Signals" in clean


def test_a_clean_briefing_is_untouched_and_reports_nothing():
    """No false positives: an ordinary briefing must pass through byte-identical."""
    ok = ("# CEREBRO — 2026-08-01\n\n## Signals\n"
          "- [[abc123|Some tool that mentions state and threads]] · github · 0.9\n"
          "- [[def456|What comes next for agents]] · rss · 0.8\n")
    clean, found = gate.sanitize(ok)
    assert found == {}
    assert clean == ok


def test_a_signal_legitimately_naming_askuserquestion_is_kept():
    """2026-07-04 carries a real Claude Code release note about AskUserQuestion.

    The gate matches the FALLBACK SENTENCE, not the word, so real content survives.
    """
    real = ("# CEREBRO — 2026-07-04\n\n## Signals\n"
            "- [v2.1.200](https://example.com) — `AskUserQuestion` no longer auto-continues\n")
    clean, found = gate.sanitize(real)
    assert found == {}
    assert clean == real


def test_the_orchestrator_actually_calls_it():
    """A gate nothing invokes is decoration."""
    import pathlib
    src = pathlib.Path("cerebro/orchestrator.py").read_text()
    assert "briefing_gate.sanitize(briefing)" in src
    assert src.index("briefing_gate.sanitize") < src.index("vault.write"), \
        "the gate must run BEFORE the briefing reaches the vault"


def test_a_hit_pages_the_operator():
    """Silent stripping is the one outcome worse than the leak."""
    import pathlib
    src = pathlib.Path("cerebro/orchestrator.py").read_text()
    assert "if leaked:" in src
    assert "push_failure" in src
