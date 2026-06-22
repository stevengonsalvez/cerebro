from __future__ import annotations

import re

from ..models import Signal
from .base import http_get, now_iso

# Launch HN — every YC company launch on HN, with its batch tag (W25 / S25 / P26 ...).
# The cleanest free "YC-backed ideas space": structured, dated, and AI/agent-heavy.
ALGOLIA = "https://hn.algolia.com/api/v1/search_by_date"
_BATCH = re.compile(r"\(YC\s+([WSFXIP]\d{2})\)", re.I)   # W=Winter S=Summer F=Fall X/I/P=newer batches


def fetch(cfg: dict, settings) -> list[Signal]:
    r = http_get(ALGOLIA, params={"query": "Launch HN", "tags": "story",
                                  "hitsPerPage": cfg.get("limit", 30)})
    out: list[Signal] = []
    for h in r.json().get("hits", []):
        title = h.get("title") or ""
        if "launch hn" not in title.lower():       # query is fuzzy — keep only real Launch HN posts
            continue
        oid = h.get("objectID")
        url = h.get("url") or f"https://news.ycombinator.com/item?id={oid}"
        m = _BATCH.search(title)
        batch = m.group(1).upper() if m else None
        out.append(Signal(
            url=url, title=title, source="yc-launch", captured=now_iso(),
            tags=["yc-launch", "launch"] + ([f"yc/{batch}"] if batch else []),
            meta={"points": h.get("points"), "hn_id": oid,
                  "comments": h.get("num_comments"), "batch": batch},
        ))
    return out
