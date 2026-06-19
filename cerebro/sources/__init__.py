from __future__ import annotations

from . import github_trending, gmail, hackernews, reddit, rss, x_bird

# name → fetch(cfg, settings) -> list[Signal]
SOURCES = {
    "hackernews": hackernews.fetch,
    "reddit": reddit.fetch,
    "github_trending": github_trending.fetch,
    "rss": rss.fetch,
    "gmail": gmail.fetch,
    "x": x_bird.fetch,
}
