from __future__ import annotations

import html
import re

from ..models import Signal
from .base import http_get, now_iso

# YC Request for Startups — the ideas YC actively wants funded ("where the puck is going").
# Server-rendered list of <h3> idea blocks; changes rarely, so the watermark dedups it after
# the first run. Scrape the idea title + anchor + description.
RFS_URL = "https://www.ycombinator.com/rfs"
_BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) cerebro/0.1"
# h3 idea title + its "#" copy-link anchor, then everything up to the next idea/footer.
_BLOCK = re.compile(
    r'<h3[^>]*>(?P<title>.*?)<span[^>]*>.*?href="(?P<anchor>#[^"]+)".*?</h3>'
    r'(?P<rest>.*?)(?=<h3[^>]*>|<footer|</main)', re.S)
_TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return html.unescape(_TAG.sub(" ", s)).replace("\xa0", " ").strip()


def fetch(cfg: dict, settings) -> list[Signal]:
    r = http_get(RFS_URL, headers={"User-Agent": _BROWSER_UA})
    out: list[Signal] = []
    for m in _BLOCK.finditer(r.text):
        title = _clean(m.group("title"))
        if not title:
            continue
        body = _clean(m.group("rest"))
        body = re.sub(r"^By\s+[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*\s*", "", body)  # drop "By <Author>" prefix
        out.append(Signal(
            url=RFS_URL + m.group("anchor"), title=f"YC RFS: {title}", source="yc-rfs",
            captured=now_iso(), clean_text=" ".join(body.split())[:600],
            tags=["yc-rfs", "ideas"], meta={"channel": "rfs"},
        ))
        if len(out) >= cfg.get("limit", 20):
            break
    return out
