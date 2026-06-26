from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

import yaml

# Feedback-learning loop (port of CondenseIt/Signex). You rate any signal note `rating: 1-5`
# in Obsidian; CEREBRO recomputes a preference profile from the vault each run (the notes ARE
# the feedback store — no extra state) and nudges the pre-rank + triage toward what you like.

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+./_-]{2,}")
_RATED = re.compile(r"^rating:\s*[0-9]", re.M)
_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "your", "into", "tool", "tools",
    "code", "coding", "build", "using", "data", "open", "source", "new", "how", "why",
}


def _terms(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)} - _STOP


def _frontmatter(txt: str) -> dict | None:
    if not txt.startswith("---"):
        return None
    end = txt.find("\n---", 3)
    if end < 0:
        return None
    try:
        return yaml.safe_load(txt[3:end]) or {}
    except yaml.YAMLError:
        return None


def load_profile(settings) -> dict:
    """Scan the vault's Signals/ notes for `rating:` and build a preference profile."""
    sig_dir = settings.vault_path / "Signals"
    liked, disliked = Counter(), Counter()
    src_r, cat_r = defaultdict(list), defaultdict(list)
    n = 0
    if sig_dir.is_dir():
        for f in sig_dir.glob("*.md"):
            try:
                txt = f.read_text(errors="replace")
            except OSError:
                continue
            if not _RATED.search(txt):           # skip unrated notes (scan whole — rating: can sit past byte 600)
                continue
            fm = _frontmatter(txt)
            if not fm:
                continue
            try:
                r = float(fm.get("rating"))
            except (TypeError, ValueError):
                continue
            n += 1
            terms = _terms(f"{fm.get('title', '')} {' '.join(map(str, fm.get('tags') or []))}")
            if r >= 4:
                liked.update(terms)
            elif r <= 2:
                disliked.update(terms)
            if fm.get("source"):
                src_r[fm["source"]].append(r)
            if fm.get("category"):
                cat_r[fm["category"]].append(r)
    return {
        "liked": [t for t, _ in liked.most_common(30)],
        "disliked": [t for t, _ in disliked.most_common(20)],
        "source_score": {s: round(statistics.mean(v), 2) for s, v in src_r.items() if v},
        "category_score": {c: round(statistics.mean(v), 2) for c, v in cat_r.items() if v},
        "n": n,
    }
