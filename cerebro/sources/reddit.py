from __future__ import annotations

import time

import feedparser

from ..models import Signal
from .base import http_get, now_iso

# ponytail: Reddit 403s the .json API for unauthenticated clients and rate-limits (429) its
# RSS when hit in bursts. Space requests + honor Retry-After once. A daily 6-sub run is fine.


def _get(url, limit):
    r = http_get(url, params={"limit": limit})
    if r.status_code == 429:
        time.sleep(min(int(r.headers.get("retry-after", "5")), 30))
        r = http_get(url, params={"limit": limit})
    return r


def fetch(cfg: dict, settings) -> list[Signal]:
    out: list[Signal] = []
    listing = cfg.get("listing", "new")
    limit = cfg.get("limit", 25)
    for i, sub in enumerate(cfg.get("subreddits", [])):
        if i:
            time.sleep(2)
        r = _get(f"https://www.reddit.com/r/{sub}/{listing}/.rss", limit)
        if r.status_code != 200:
            continue
        for e in feedparser.parse(r.content).entries[:limit]:
            out.append(Signal(
                url=e.get("link", ""), title=e.get("title", ""), source="reddit",
                captured=now_iso(),
                meta={"sub": sub, "published": e.get("published", "")},
            ))
    return out
