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


def _keep(s: Signal, threshold: float, keep_sources) -> bool:
    """beast: keep all keep_sources regardless of score (still scored)."""
    return s.score >= threshold or s.source in keep_sources


def triage(signals: list[Signal], settings, batch: int = 60, meter: dict | None = None,
           profile: dict | None = None, keep_sources=None) -> list[Signal]:
    """Score + categorize via Claude Code (haiku) in batches, keep score >= threshold, sort desc.

    keep_sources: sources exempt from the score-drop (still scored, never cut). beast: {"x"}."""
    keep_sources = keep_sources or set()
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
            if s.source in keep_sources:   # beast: a failed/empty triage batch must not silently drop X
                out.append(s)
            continue
        s.score = float(r.get("score", 0) or 0)
        s.category = r.get("category", "") or ""
        s.tags = r.get("tags") or []
        s.meta["reason"] = (r.get("reason") or "").strip()
        if _keep(s, threshold, keep_sources):
            out.append(s)
    out.sort(key=lambda s: s.score, reverse=True)
    return out


if __name__ == "__main__":   # offline self-check: keep_sources exempts low-score signals from the drop
    lo_x = Signal(url="x1", title="t", source="x"); lo_x.score = 0.1
    lo_rss = Signal(url="r1", title="t", source="rss"); lo_rss.score = 0.1
    threshold = 0.5
    keep_sources = {"x"}
    out = [s for s in (lo_x, lo_rss) if _keep(s, threshold, keep_sources)]
    assert lo_x in out, "low-score X must survive when x in keep_sources"
    assert lo_rss not in out, "low-score rss must be dropped"
    print("triage self-check OK")
