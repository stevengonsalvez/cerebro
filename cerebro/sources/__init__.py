from __future__ import annotations

from . import github_trending, gmail, hackernews, ossinsight, reddit, rss, x_twscrape

# name → fetch(cfg, settings) -> list[Signal]
SOURCES = {
    "hackernews": hackernews.fetch,
    "reddit": reddit.fetch,
    "github_trending": github_trending.fetch,
    "ossinsight": ossinsight.fetch,
    "rss": rss.fetch,
    "gmail": gmail.fetch,
    "x": x_twscrape.fetch,
}
