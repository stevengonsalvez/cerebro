from __future__ import annotations

import re

from ..models import Signal
from .base import http_get, now_iso

BASE = "https://swipe.md"
ISSUE = re.compile(
    r"(?P<published>[A-Z][a-z]+ \d{1,2}, \d{4})\s+(?P<title>[^\n]+)\s+"
    r"(?P<summary>.*?)\]\((?P<url>https://swipe\.md/issues/[^)]+)\)",
    re.S,
)
TOOL = re.compile(
    r"\d+\.\s+\[(?P<category>[^\n]+)\s+##\s*(?P<title>[^\n]+)\s+"
    r"(?P<summary>.*?)\]\((?P<url>https://swipe\.md/tools/[^)]+)\)",
    re.S,
)


def fetch(cfg: dict, settings) -> list[Signal]:
    out = _signals(http_get(f"{BASE}/issues.md").text, ISSUE, "issue", cfg.get("issues_limit", 8))
    out += _signals(http_get(f"{BASE}/tools.md").text, TOOL, "tool", cfg.get("tools_limit", 12))
    return out


def _signals(markdown: str, pattern: re.Pattern, kind: str, limit: int) -> list[Signal]:
    out: list[Signal] = []
    for match in pattern.finditer(markdown):
        values = {key: " ".join(value.split()) for key, value in match.groupdict().items()}
        if not values["title"] or not values["url"]:
            continue
        out.append(Signal(
            url=values["url"], title=f"Swipe: {values['title']}", source="swipe",
            captured=now_iso(), clean_text=values["summary"][:2000],
            topic_tags=["ai-skills", "workflows"], source_tags=["swipe", f"swipe/{kind}"],
            meta={"kind": kind, "published": values.get("published", ""), "category": values.get("category", "")},
        ))
        if len(out) >= limit:
            break
    return out
