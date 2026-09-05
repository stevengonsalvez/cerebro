"""F071 — the briefing must not publish the operator's assistant conventions.

WHY THIS EXISTS, measured rather than imagined. `cerebro/llm/claude.py` shells out to
`claude -p`, which auto-discovers CLAUDE.md, so every digest call inherits whatever the
OPERATOR keeps in `~/.claude/CLAUDE.md`. On 2026-09-02 that file grew — `cache_read` in the
briefing frontmatter jumped 36,487 to 295,307 the same morning — and the model began
obeying its `turn_end_block` rule. Six briefings shipped to the public vault and the live
site carrying a `| thread | state | next |` table, `[fact]` and `[inference]` bullets,
`next: commit vault/Daily/... via /commit`, and on 09-05 an "AskUserQuestion tool not in
this session" preamble with a numbered question addressed to nobody.

THE PROMPT-LEVEL FIX IS NOT A GUARANTEE. `claude.PERSONA_OVERRIDE` tells the model it is a
content backend, and its tests assert the flag is PASSED — not that the output is clean. A
model can drift, a flag can be dropped in a refactor, and the operator's memory file will
keep changing without anybody thinking about this pipeline. The prompt is the request; this
is the check on what actually came back.

STRIP AND ANNOUNCE, NOT FAIL. A hard failure would mean no briefing at all on a day when
the signals were fine — and in the real incident they always were: all 50/22/50/25/25/25
signal bullets were correct, only the surrounding commentary did not belong. So the
artefacts are removed, the briefing publishes, and the count travels back to the caller so
the run can page. Silent stripping is the one outcome worse than the leak, because the next
recurrence would never be noticed.
"""
from __future__ import annotations

import re

#: Each pattern was taken from text that ACTUALLY REACHED READERS. This is not a guess at
#: what an assistant might say; it is the incident, encoded.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # The turn-end state table: header row, separator, and every row under it.
    ("turn_end_table",
     re.compile(r'\n\|[^\n]*\bthread\b[^\n]*\|[^\n]*\bstate\b[^\n]*\|[^\n]*\bnext\b[^\n]*\|\n'
                r'\|[-\s|:]+\|\n(?:\|[^\n]*\|\n)*', re.I)),
    # The single recommendation line that follows it.
    ("next_line", re.compile(r'^next:[^\n]*\n', re.M | re.I)),
    # Evidence-tagged bullets.
    ("fact_bullet", re.compile(r'^[-*][^\n]*\[(?:fact|inference)\][^\n]*\n', re.M | re.I)),
    # The plaintext fallback the option_presentation rule asks for when the tool is absent.
    ("askuserquestion", re.compile(r'^[^\n]*AskUserQuestion[^\n]*not in this session[^\n]*\n', re.M | re.I)),
    ("numbered_question", re.compile(r'^#{2,4}\s*Question:[^\n]*\n(?:^\s*\d+\.[^\n]*\n)*', re.M | re.I)),
    # Status sentences about the pipeline's own file handling.
    ("self_status",
     re.compile(r'^(?:File written:|Briefing written,)[^\n]*\n', re.M)),
)


def scan(text: str) -> dict[str, int]:
    """Which artefacts are present, and how many of each. Read-only."""
    return {name: len(rx.findall(text)) for name, rx in PATTERNS if rx.search(text)}


def sanitize(text: str) -> tuple[str, dict[str, int]]:
    """Remove every artefact. Returns the cleaned briefing and what was taken out.

    The caller MUST surface a non-empty second value. A recurrence that nobody hears about
    is the failure this module exists to prevent.
    """
    found = scan(text)
    if not found:
        return text, {}
    out = text
    for _name, rx in PATTERNS:
        out = rx.sub("", out)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out, found
