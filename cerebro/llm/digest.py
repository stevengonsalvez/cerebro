from __future__ import annotations

import pathlib

from ..models import Signal
from . import claude

PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "prompts"


def digest(top: list[Signal], settings) -> str:
    """The user-facing 'explain-to-me' briefing markdown, via Claude Code (sonnet)."""
    if not top:
        return "_No signals cleared the relevance bar today._"
    items = "\n".join(
        f"- [{s.category or 'misc'}] {s.title} ({s.source}) {s.url}\n  {s.clean_text[:400]}"
        for s in top
    )
    prompt = (PROMPTS / "digest.md").read_text().format(items=items, count=len(top))
    model = settings.models.get("digest", "sonnet")
    return claude.run(prompt, model).strip()
