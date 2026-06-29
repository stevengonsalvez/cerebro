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


def _score_batch(signals, base, matrix, tmpl, model, meter) -> dict:
    items = [
        {"id": base + j, "title": s.title[:200], "snippet": s.clean_text[:200], "source": s.source}
        for j, s in enumerate(signals)
    ]
    prompt = tmpl.format(matrix=matrix, items=json.dumps(items, ensure_ascii=False))
    try:
        results = _extract_json(claude.run(prompt, model, meter))
    except (json.JSONDecodeError, AttributeError):
        results = _extract_json(claude.run(prompt + "\n\nReturn ONLY the JSON array. No other text.", model, meter))
    return {r["id"]: r for r in results if isinstance(r, dict) and "id" in r}


def _prefs_block(profile: dict | None) -> str:
    if not profile or not profile.get("n"):
        return ""
    lines = []
    if profile.get("liked"):
        lines.append("rated-high topics (boost): " + ", ".join(profile["liked"][:15]))
    if profile.get("disliked"):
        lines.append("rated-low topics (penalize): " + ", ".join(profile["disliked"][:10]))
    if profile.get("source_score"):
        lines.append("source trust 1-5: " + ", ".join(f"{k}={v}" for k, v in profile["source_score"].items()))
    if not lines:
        return ""
    return "\n\nUSER FEEDBACK (Stevie rated past signals — weight accordingly):\n- " + "\n- ".join(lines)


def triage(signals: list[Signal], settings, batch: int = 60, meter: dict | None = None,
           profile: dict | None = None) -> list[Signal]:
    """Score + categorize via Claude Code (haiku) in batches, keep score >= threshold, sort desc."""
    if not signals:
        return []
    matrix = _matrix_block(settings.matrix) + _prefs_block(profile)
    tmpl = (PROMPTS / "triage.md").read_text()
    model = settings.models.get("triage", "haiku")
    by_id: dict = {}
    for start in range(0, len(signals), batch):
        try:
            by_id.update(_score_batch(signals[start:start + batch], start, matrix, tmpl, model, meter))
        except (claude.CerebroLLMError, json.JSONDecodeError, ValueError) as e:
            print(f"[warn] triage batch {start} failed: {e}")   # batch failure must not discard the whole run

    threshold = settings.depth.get("score_threshold", 0.5)
    out: list[Signal] = []
    for i, s in enumerate(signals):
        r = by_id.get(i)
        if not r:
            continue
        pre_source_tags = list(s.source_tags or s.tags or [])
        s.score = float(r.get("score", 0) or 0)
        s.category = r.get("category", "") or ""
        s.topic_tags = r.get("topic_tags") or r.get("tags") or []
        s.source_tags = pre_source_tags
        s.entity_tags = r.get("entities") or s.entity_tags
        s.meta["explore_score"] = r.get("explore_score", s.meta.get("explore_score"))
        s.meta["explore_angle"] = r.get("explore_angle", s.meta.get("explore_angle", ""))
        s.meta["why_now"] = r.get("why_now", s.meta.get("why_now", ""))
        s.merge_tags()
        s.meta["reason"] = (r.get("reason") or "").strip()
        if s.score >= threshold:
            out.append(s)
    out.sort(key=lambda s: s.score, reverse=True)
    return out
