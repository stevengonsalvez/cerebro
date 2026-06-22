from __future__ import annotations

import html
import json
import pathlib
import re

from ..llm import claude
from ..models import Signal
from ..sources.base import http_get

# Port of Horizon's "read the conversation": for the top-N signals that have a comment thread,
# pull the discussion and summarize the community take in one line. HN only for now — Algolia's
# items API is free; Reddit comments hit the same 403 auth wall as its listing.

PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "prompts"
_TAG = re.compile(r"<[^>]+>")


def _extract_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\[.*\]", text, re.S)
    return json.loads(m.group(0) if m else text)


def _hn_comments(hn_id, limit: int = 6) -> list[str]:
    try:
        r = http_get(f"https://hn.algolia.com/api/v1/items/{hn_id}")
        if r.status_code != 200:
            return []
        children = r.json().get("children") or []
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for c in children:
        t = c.get("text")
        if not t:
            continue
        txt = html.unescape(_TAG.sub("", t)).strip()
        if len(txt) > 30:
            out.append(txt[:400])
        if len(out) >= limit:
            break
    return out


def enrich(top: list[Signal], settings, meter: dict | None = None) -> list[Signal]:
    """Attach a one-line community discussion summary (meta['discussion']) to top-N HN signals."""
    items = []
    for i, s in enumerate(top):
        if s.source in ("hackernews", "show_hn", "yc-launch") and s.meta.get("hn_id"):
            cm = _hn_comments(s.meta["hn_id"])
            if cm:
                items.append({"id": i, "title": s.title[:120], "comments": cm})
    if not items:
        return top
    prompt = (PROMPTS / "comments.md").read_text().format(
        items=json.dumps(items, ensure_ascii=False)[:12000]
    )
    try:
        data = _extract_json(claude.run(prompt, settings.models.get("triage", "haiku"), meter))
    except Exception:  # noqa: BLE001
        return top
    by_id = {d["id"]: (d.get("summary") or "").strip() for d in data if isinstance(d, dict) and "id" in d}
    for i, s in enumerate(top):
        if by_id.get(i):
            s.meta["discussion"] = by_id[i]
    return top
