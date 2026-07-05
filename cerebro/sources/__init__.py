from __future__ import annotations

from . import (
    github_search, github_trending, gmail, hackernews, ossinsight, reddit, rss,
    showhn, x_twscrape, yclaunches, ycrfs,
)

# name → fetch(cfg, settings) -> list[Signal]
SOURCES = {
    "hackernews": hackernews.fetch,
    "showhn": showhn.fetch,
    "yc_launches": yclaunches.fetch,
    "yc_rfs": ycrfs.fetch,
    "reddit": reddit.fetch,
    "github_trending": github_trending.fetch,
    "github_search": github_search.fetch,
    "ossinsight": ossinsight.fetch,
    "rss": rss.fetch,
    "gmail": gmail.fetch,
    "x": x_twscrape.fetch,
}
