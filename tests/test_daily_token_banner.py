"""The published daily page states the tokens spent producing it, above the briefing."""
from cerebro.models import RunStats
from cerebro.sink import vault


def test_token_banner_sits_between_title_and_briefing():
    stats = RunStats(run_id="t", input_tokens=1000, output_tokens=200, cache_read=30000,
                     cache_creation=4000, cost_usd=1.5, llm_calls=12)
    note = vault._daily("2026-09-28", "BRIEFING BODY", [], stats)
    body = note.split("---\n", 2)[2]
    assert body.index("# CEREBRO") < body.index("35,200 tokens") < body.index("BRIEFING BODY")
    assert "across 12 Claude calls" in body
    assert "tokens_total: 35200\n" in note


def test_no_banner_without_stats():
    assert "> Researched" not in vault._daily("2026-09-28", "B", [], None)
