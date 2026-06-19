from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Signal:
    """One candidate item flowing through the funnel. Sources produce these;
    every downstream stage mutates and passes them on."""
    url: str
    title: str
    source: str                       # hackernews|reddit|github|rss|gmail|x
    canonical_url: str = ""           # set in dedup
    url_hash: str = ""                # set in dedup
    raw_html: str = ""                # if fetched
    clean_text: str = ""              # set in extract
    simhash: int = 0                  # set in dedup
    score: float = 0.0                # set by triage (0..1)
    category: str = ""                # set by triage
    tags: list[str] = field(default_factory=list)
    captured: str = ""                # ISO8601, set at fetch
    meta: dict = field(default_factory=dict)   # points/author/stars/sender


@dataclass
class RunStats:
    run_id: str
    raw: int = 0
    after_dedup: int = 0
    after_triage: int = 0
    digested: int = 0
    dry_run: bool = True
    x_ok: bool = True
    error: str = ""
