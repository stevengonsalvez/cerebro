from __future__ import annotations

import re

from ..models import Signal

# ponytail: cheap deterministic pre-rank BEFORE the LLM triage — keyword/term overlap against
# the interest matrix. Trims the long tail of zero-match noise so Haiku scores ~top-K, not all
# ~500 candidates (roughly halves the run's tokens). The LLM still does the real semantic call;
# this only drops items with no interest-term signal at all. Inspired by CondenseIt's pre-scoring.

_STOP = {
    "tools", "tool", "your", "that", "with", "from", "into", "this", "they", "them", "what",
    "when", "which", "their", "about", "more", "less", "code", "coding", "build", "using",
    "data", "open", "source", "model", "models", "agent", "agents",  # too generic across all cats
}


def _matrix_terms(matrix: dict) -> set[str]:
    terms: set[str] = set()
    for c in matrix.get("categories", []):
        for t in c.get("tags", []):
            terms.update(re.findall(r"\w+", t.lower()))
        terms.update(w for w in re.findall(r"\w+", c.get("desc", "").lower()) if len(w) > 3)
    return terms - _STOP


def _score(sig: Signal, terms: set[str]) -> int:
    words = set(re.findall(r"\w+", f"{sig.title} {sig.clean_text}".lower()))
    return len(words & terms)


def prerank(signals: list[Signal], settings, keep: int) -> list[Signal]:
    """Keep the top `keep` candidates by interest-term overlap (records the score in meta)."""
    if len(signals) <= keep:
        return signals
    terms = _matrix_terms(settings.matrix)
    for s in signals:
        s.meta["prerank"] = _score(s, terms)
    return sorted(signals, key=lambda s: s.meta.get("prerank", 0), reverse=True)[:keep]


if __name__ == "__main__":  # ponytail: one runnable check
    from ..config import load
    s = load()
    terms = _matrix_terms(s.matrix)
    assert "tui" in terms or "llm" in {t for t in terms}, sorted(terms)[:20]
    a = Signal(url="u1", title="New Claude Code subagent token caching trick", source="hn")
    b = Signal(url="u2", title="My cat photos from the weekend", source="rss")
    assert _score(a, terms) > _score(b, terms)
    print("prerank self-check OK · matrix terms:", len(terms))
