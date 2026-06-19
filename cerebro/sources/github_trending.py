from __future__ import annotations

import html
import re

from ..models import Signal
from .base import http_get, now_iso

# ponytail: GitHub has no official trending API, so scrape github.com/trending. Brittle to
# GitHub HTML changes, but it's the only honest "trending" — the search-by-stars proxy
# missed the point (it surfaced brand-new repos, not what's actually surging).
H2_RE = re.compile(r'<h2 class="h3 lh-condensed">(.*?)</h2>', re.S)
REPO_RE = re.compile(r'href="/([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)"')
DESC_RE = re.compile(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', re.S)
STARS_RE = re.compile(r'([\d,]+)\s+stars today')


def fetch(cfg: dict, settings) -> list[Signal]:
    sinces = cfg.get("since", "daily")
    if isinstance(sinces, str):
        sinces = [sinces]
    out: list[Signal] = []
    seen: set[str] = set()        # dedup repos trending in >1 window
    for since in sinces:
        for lang in (cfg.get("languages") or [""]):
            url = f"https://github.com/trending/{lang}" if lang else "https://github.com/trending"
            r = http_get(url, params={"since": since})
            if r.status_code != 200:
                continue
            for block in r.text.split('<article class="Box-row">')[1:]:
                h2 = H2_RE.search(block)      # repo link lives in the heading, not sponsor/avatar links
                m = REPO_RE.search(h2.group(1)) if h2 else None
                if not m or m.group(1) in seen:
                    continue
                repo = m.group(1)
                seen.add(repo)
                d = DESC_RE.search(block)
                desc = html.unescape(re.sub("<[^>]+>", "", d.group(1)).strip()) if d else ""
                st = STARS_RE.search(block)
                out.append(Signal(
                    url=f"https://github.com/{repo}",
                    title=f"{repo}: {desc}".strip().rstrip(":"), source="github", captured=now_iso(),
                    meta={"repo": repo, "stars": st.group(1) if st else None,
                          "window": since, "lang": lang or None},
                ))
    return out
