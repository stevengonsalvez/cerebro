from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping

from ..models import Signal

_RATED = re.compile(r"^rating:\s*[0-9]", re.M)   # a note you've scored — never clobber it


def _alias(title: str) -> str:
    # collapse newlines/whitespace too — x titles are raw tweet text and would otherwise
    # break the YAML frontmatter scalar and the daily-index wikilink across lines.
    return " ".join(title.replace("|", " ").replace("[", "(").replace("]", ")").split())


def _yaml_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace('"', "'")
    return f'"{" ".join(text.split())}"'


def _yaml_list(values: list[str]) -> str:
    return "[" + ", ".join(str(v) for v in values if str(v).strip()) + "]"


def _meta_frontmatter(meta: Mapping) -> str:
    allowed = (
        "author", "likes", "retweets", "replies", "views", "query", "via_tweet",
        "exploded", "repo", "stars", "forks", "language", "entity_type",
        "entity_id", "github_query", "explore_score", "explore_angle", "why_now",
    )
    rows = []
    for key in allowed:
        if key in meta and meta[key] not in (None, "", [], {}):
            rows.append(f"{key}: {_yaml_value(meta[key])}")
    return ("\n".join(rows) + "\n") if rows else ""


def _atomic(s: Signal) -> str:
    s.artifact_tags = sorted(set((s.artifact_tags or []) + ["cerebro/signal"]))
    s.merge_tags()
    body = (s.clean_text[:600].strip() or s.title)
    reason = " ".join((s.meta.get("reason") or "").replace('"', "'").split())
    rline = f'reason: "{reason}"\n' if reason else ""
    rquote = f"> {reason}\n\n" if reason else ""
    disc = (s.meta.get("discussion") or "").strip()
    dsec = f"\n\n## Community take\n{disc}\n" if disc else ""
    return (
        f"---\n"
        f'title: "{_alias(s.title).replace(chr(34), chr(39))[:200]}"\n'
        f"category: {s.category or 'misc'}\n"
        f"tags: {_yaml_list(s.tags)}\n"
        f"topic_tags: {_yaml_list(s.topic_tags)}\n"
        f"source_tags: {_yaml_list(s.source_tags)}\n"
        f"entity_tags: {_yaml_list(s.entity_tags)}\n"
        f"artifact_tags: {_yaml_list(s.artifact_tags)}\n"
        f"workflow_tags: {_yaml_list(s.workflow_tags)}\n"
        f"source: {s.source}\n"
        f"url: {s.url}\n"
        f"score: {s.score:.2f}\n"
        f"{rline}"
        f"{_meta_frontmatter(s.meta)}"
        f"captured: {s.captured}\n"
        f"rating:\n"               # ← set 1-5 in Obsidian to teach CEREBRO what you value
        f"---\n"
        f"# {s.title}\n\n{rquote}{body}{dsec}\n\n[Open ↗]({s.url})\n"
    )


def _sources_footer(signals: list[Signal], stats=None) -> str:
    """Provenance footnote: which source fetched what, what reached the briefing, + citations."""
    in_brief = Counter(s.source for s in signals)
    fetched = dict(getattr(stats, "per_source", {}) or {})
    rows = sorted(set(fetched) | set(in_brief), key=lambda k: (-in_brief.get(k, 0), -fetched.get(k, 0), k))
    table = "\n".join(
        f"| {k} | {fetched.get(k, '·')} | {in_brief.get(k, 0)} |" for k in rows
    )
    total_fetched = sum(fetched.values())
    cites = "\n".join(
        f"{i}. `{s.source}` · [{_alias(s.title)[:90]}]({s.url}) · score {s.score:.2f}"
        for i, s in enumerate(signals, 1)
    )
    return (
        "\n---\n\n## Sources & citations\n\n"
        "| source | fetched | in briefing |\n|---|--:|--:|\n"
        f"{table}\n| **total** | **{total_fetched}** | **{len(signals)}** |\n\n"
        f"### Citations\n{cites}\n"
    )


def _daily(date: str, briefing: str, signals: list[Signal], stats=None) -> str:
    index = "\n".join(
        f"- [[{s.url_hash}|{_alias(s.title)}]] · {s.source} · {s.score:.2f}"
        for s in signals
    )
    usage = ""
    if stats is not None:
        usage = (
            f"tokens_input: {stats.input_tokens}\n"
            f"tokens_output: {stats.output_tokens}\n"
            f"cache_read: {stats.cache_read}\n"
            f"cache_creation: {stats.cache_creation}\n"
            f"tokens_total: {stats.input_tokens + stats.output_tokens + stats.cache_read + stats.cache_creation}\n"
            f"cost_usd: {stats.cost_usd:.4f}\n"
            f"llm_calls: {stats.llm_calls}\n"
        )
    return (
        f"---\ndate: {date}\ntype: cerebro-briefing\ncount: {len(signals)}\n{usage}---\n"
        f"# CEREBRO — {date}\n\n{briefing}\n\n## Signals\n{index}\n"
        f"{_sources_footer(signals, stats)}"
    )


def write(date: str, briefing: str, signals: list[Signal], settings, stats=None) -> dict:
    """Daily briefing note + one atomic note per signal. Dry-run → _scratch/.
    Idempotent: atomic filenames are the url_hash; the daily note overwrites."""
    root = (settings.vault_path / "_scratch") if settings.dry_run else settings.vault_path
    daily_dir, sig_dir = root / "Daily", root / "Signals"
    daily_dir.mkdir(parents=True, exist_ok=True)
    sig_dir.mkdir(parents=True, exist_ok=True)
    for s in signals:
        p = sig_dir / f"{s.url_hash}.md"
        if p.exists() and _RATED.search(p.read_text(errors="replace")):
            continue                                  # preserve your rating (scan whole note — it's already in memory)
        p.write_text(_atomic(s))
    daily = daily_dir / f"{date}.md"
    daily.write_text(_daily(date, briefing, signals, stats))
    return {"daily": str(daily), "signals_dir": str(sig_dir), "n": len(signals)}
