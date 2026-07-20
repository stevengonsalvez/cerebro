from __future__ import annotations

import time

import feedparser

from ..models import Signal
from .base import now_iso
from .reddit import _get  # reuse existing 429/Retry-After signature: _get(url, limit)

# ponytail: RSS payload carries no score, so no min_score filter is possible here.
# Volume is bounded by `limit` alone; score filtering would need an authenticated client.


def fetch(cfg: dict, settings) -> list[Signal]:
    users = [_clean(u) for u in (cfg.get("users") or []) if str(u).strip()]
    if not users:
        return []

    limit = int(cfg.get("limit", 10))
    out: list[Signal] = []
    for i, user in enumerate(users):
        if i:
            time.sleep(2)  # burst-avoidance, per reddit.py:27-28
        r = _get(f"https://www.reddit.com/user/{user}/submitted/.rss", limit)
        if r.status_code != 200:  # suspended / 404 / rate-limited — skip silently
            continue
        for e in feedparser.parse(r.content).entries[:limit]:
            out.append(Signal(
                url=e.get("link", ""),
                title=e.get("title", ""),
                source="reddit",
                captured=now_iso(),
                source_tags=["reddit/cracked-dev"],
                entity_tags=[f"developer/{user}"],
                meta={"dev": user, "published": e.get("published", "")},
            ))
    return out


def _clean(v) -> str:
    # ponytail: explicit prefix check, NOT lstrip("u/") — lstrip strips a character set,
    # so "uuu_dev" / "user123" would be mangled. Strip a leading "u/" once, nothing else.
    s = str(v).strip().lstrip("@")
    return s[2:] if s.lower().startswith("u/") else s
