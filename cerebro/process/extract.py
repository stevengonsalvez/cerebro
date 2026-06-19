from __future__ import annotations

import trafilatura

from ..models import Signal
from ..sources.base import http_get

# ponytail: extract is the expensive stage (one HTTP fetch per item), so the orchestrator
# runs it on the post-triage top-N only — never the full raw set. Items that already carry
# text (rss summary, reddit selftext, tweets) or html (gmail) skip the fetch.


def enrich(signals: list[Signal]) -> list[Signal]:
    for s in signals:
        if len(s.clean_text) > 200:
            continue
        html = s.raw_html
        if not html and s.url.startswith("http"):
            try:
                r = http_get(s.url)
                html = r.text if r.status_code == 200 else ""
            except Exception:
                html = ""
        if html:
            text = trafilatura.extract(html) or ""
            if text:
                s.clean_text = text[:4000]
    return signals
