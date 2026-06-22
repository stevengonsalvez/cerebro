from __future__ import annotations

from ..models import Signal
from .base import http_get, now_iso

# Show HN as its own channel — maker launches & demos, kept separate from the front-page
# HN bucket so they're a distinct lane in triage + the vault (tagged `showcase`).
ALGOLIA = "https://hn.algolia.com/api/v1/search"


def fetch(cfg: dict, settings) -> list[Signal]:
    r = http_get(ALGOLIA, params={"tags": "show_hn", "hitsPerPage": cfg.get("limit", 40)})
    out: list[Signal] = []
    for h in r.json().get("hits", []):
        oid = h.get("objectID")
        url = h.get("url") or f"https://news.ycombinator.com/item?id={oid}"
        out.append(Signal(
            url=url, title=h.get("title") or "", source="show_hn", captured=now_iso(),
            tags=["showcase"],
            meta={"points": h.get("points"), "hn_id": oid, "comments": h.get("num_comments")},
        ))
    return out
