from __future__ import annotations

import re

from ..models import Signal

# Lenient by design — only drop obvious non-content. Real relevance filtering is the
# triage pass, which is cheap enough to over-feed. ponytail: don't reinvent langdetect.
_NONASCII = re.compile(r"[^\x00-\x7F]")


def _mostly_non_english(text: str) -> bool:
    if not text:
        return False
    return len(_NONASCII.findall(text)) > len(text) * 0.5


def filter(signals: list[Signal]) -> list[Signal]:
    out: list[Signal] = []
    for s in signals:
        title = s.title.strip()
        if not title or len(title) < 4:
            continue
        if _mostly_non_english(title):
            continue
        out.append(s)
    return out


if __name__ == "__main__":  # ponytail: one runnable check
    from ..models import Signal as S
    kept = filter([
        S(url="u1", title="Claude Code 2.1 ships subagents", source="hn"),
        S(url="u2", title="", source="hn"),                       # empty → drop
        S(url="u3", title="日本語のニュースだけのタイトル例です", source="rss"),  # non-EN → drop
    ])
    assert len(kept) == 1, [s.title for s in kept]
    print("junkgate self-check OK")
