from __future__ import annotations

import json
import pathlib
import re

from ..models import Signal
from . import claude

PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "prompts"


def _matrix_block(matrix: dict) -> str:
    return "\n".join(
        f"- {c['key']}: {c['desc'].strip()} (tags: {', '.join(c['tags'])})"
        for c in matrix.get("categories", [])
    )


def _extract_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\[.*\]", text, re.S)
    return json.loads(m.group(0) if m else text)


def triage(signals: list[Signal], settings) -> list[Signal]:
    """Score + categorize via Claude Code (haiku), keep score >= threshold, sort desc."""
    if not signals:
        return []
    items = [
        {"id": i, "title": s.title[:200], "snippet": s.clean_text[:200], "source": s.source}
        for i, s in enumerate(signals)
    ]
    prompt = (PROMPTS / "triage.md").read_text().format(
        matrix=_matrix_block(settings.matrix),
        items=json.dumps(items, ensure_ascii=False),
    )
    model = settings.models.get("triage", "haiku")
    raw = claude.run(prompt, model)
    try:
        results = _extract_json(raw)
    except (json.JSONDecodeError, AttributeError):
        raw = claude.run(prompt + "\n\nReturn ONLY the JSON array. No other text.", model)
        results = _extract_json(raw)

    by_id = {r["id"]: r for r in results if isinstance(r, dict) and "id" in r}
    threshold = settings.depth.get("score_threshold", 0.5)
    out: list[Signal] = []
    for i, s in enumerate(signals):
        r = by_id.get(i)
        if not r:
            continue
        s.score = float(r.get("score", 0) or 0)
        s.category = r.get("category", "") or ""
        s.tags = r.get("tags") or []
        if s.score >= threshold:
            out.append(s)
    out.sort(key=lambda s: s.score, reverse=True)
    return out
