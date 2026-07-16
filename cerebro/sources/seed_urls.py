from __future__ import annotations

from ..models import Signal
from .base import now_iso


def fetch(cfg: dict, settings) -> list[Signal]:
    """Return manually curated one-off URLs as first-class signals.

    Use for explicit sources Stevie wants Cerebro to track even if the source feed
    already exists; this keeps the exact article pinned until dedup marks it seen.
    """
    out: list[Signal] = []
    for item in cfg.get("items", []):
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        if not url or not title:
            continue
        tags = [str(t).strip() for t in item.get("tags", []) if str(t).strip()]
        note = str(item.get("note", "")).strip()
        out.append(
            Signal(
                url=url,
                title=title,
                source="seed_urls",
                captured=now_iso(),
                clean_text=note,
                topic_tags=tags,
                meta={"seed": True, "reason": note},
            )
        )
    return out
