from __future__ import annotations

import feedparser

from ..models import Signal
from .base import now_iso

# ponytail: no ETag/Last-Modified persistence yet — feedparser refetches whole feed each run.
# Fine at this scale; add conditional-GET if feed count grows.


def fetch(cfg: dict, settings) -> list[Signal]:
    out: list[Signal] = []
    limit = cfg.get("limit", 20)
    for feed in cfg.get("feeds", []):
        d = feedparser.parse(feed)
        for e in d.entries[:limit]:
            out.append(Signal(
                url=e.get("link", ""), title=e.get("title", ""), source="rss",
                captured=now_iso(), clean_text=(e.get("summary") or "")[:2000],
                meta={"feed": feed, "published": e.get("published", "")},
            ))
    return out
