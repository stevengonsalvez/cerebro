from __future__ import annotations

from ..models import Signal
from .base import http_get, now_iso

# ponytail: Algolia front_page/show_hn = 1 request per list, vs ~120 firebase item GETs.
ALGOLIA = "https://hn.algolia.com/api/v1/search"
TAGMAP = {"topstories": "front_page", "showstories": "show_hn"}


def fetch(cfg: dict, settings) -> list[Signal]:
    out: list[Signal] = []
    for lst in cfg.get("lists", ["topstories"]):
        tag = TAGMAP.get(lst, lst)
        r = http_get(ALGOLIA, params={"tags": tag, "hitsPerPage": cfg.get("limit", 60)})
        for h in r.json().get("hits", []):
            oid = h.get("objectID")
            url = h.get("url") or f"https://news.ycombinator.com/item?id={oid}"
            out.append(Signal(
                url=url, title=h.get("title") or "", source="hackernews", captured=now_iso(),
                meta={"points": h.get("points"), "hn_id": oid, "comments": h.get("num_comments")},
            ))
    return out
