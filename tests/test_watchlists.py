from __future__ import annotations

from cerebro.gitintel.watchlists import read_watchlist


def test_read_watchlist_frontmatter(tmp_path):
    p = tmp_path / "git-search.md"
    p.write_text("""---
type: cerebro-watchlist
---

- github profile into cursor skill generator
- agent skills marketplace
""")

    assert read_watchlist(p) == [
        "github profile into cursor skill generator",
        "agent skills marketplace",
    ]
