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
    topic_tags: list[str] = field(default_factory=list)
    source_tags: list[str] = field(default_factory=list)
    entity_tags: list[str] = field(default_factory=list)
    artifact_tags: list[str] = field(default_factory=list)
    workflow_tags: list[str] = field(default_factory=list)
    captured: str = ""                # ISO8601, set at fetch
    meta: dict = field(default_factory=dict)   # points/author/stars/sender

    def merge_tags(self) -> list[str]:
        """Return Obsidian-compatible tags while preserving typed tag layers."""
        if not self.source_tags and self.tags and not self.topic_tags:
            self.source_tags = list(self.tags)
        merged = []
        for values in (
            self.topic_tags,
            self.source_tags,
            self.entity_tags,
            self.artifact_tags,
            self.workflow_tags,
            self.tags,
        ):
            merged.extend(values or [])
        self.tags = sorted({str(t).strip() for t in merged if str(t).strip()})
        return self.tags


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
    per_source: dict = field(default_factory=dict)   # source name → items fetched this run
    # LLM token usage (summed across all claude -p calls this run)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
