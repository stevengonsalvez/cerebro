from __future__ import annotations

from types import SimpleNamespace

from cerebro.sources import SOURCES
from cerebro.sources.seed_urls import fetch


def test_seed_urls_fetches_configured_articles_as_signals() -> None:
    cfg = {
        "items": [
            {
                "title": "Have your agent record video demos of its work with shot-scraper video",
                "url": "https://simonwillison.net/2026/Jun/30/shot-scraper-video/?utm_source=substack&utm_medium=email",
                "tags": ["agent-evidence", "demo-video", "shot-scraper"],
                "note": "Agents can record proof-of-work browser videos with shot-scraper video.",
            }
        ]
    }

    got = fetch(cfg, SimpleNamespace())

    assert len(got) == 1
    assert got[0].source == "seed_urls"
    assert got[0].title == "Have your agent record video demos of its work with shot-scraper video"
    assert got[0].url == "https://simonwillison.net/2026/Jun/30/shot-scraper-video/?utm_source=substack&utm_medium=email"
    assert got[0].topic_tags == ["agent-evidence", "demo-video", "shot-scraper"]
    assert got[0].clean_text == "Agents can record proof-of-work browser videos with shot-scraper video."
    assert got[0].meta["seed"] is True


def test_seed_urls_source_is_registered() -> None:
    assert SOURCES["seed_urls"] is fetch
