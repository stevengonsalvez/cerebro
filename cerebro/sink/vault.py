from __future__ import annotations

import re

from ..models import Signal

_RATED = re.compile(r"^rating:\s*[0-9]", re.M)   # a note you've scored — never clobber it


def _alias(title: str) -> str:
    return title.replace("|", " ").replace("[", "(").replace("]", ")")


def _atomic(s: Signal) -> str:
    body = (s.clean_text[:600].strip() or s.title)
    reason = (s.meta.get("reason") or "").replace('"', "'")
    rline = f'reason: "{reason}"\n' if reason else ""
    rquote = f"> {reason}\n\n" if reason else ""
    disc = (s.meta.get("discussion") or "").strip()
    dsec = f"\n\n## Community take\n{disc}\n" if disc else ""
    return (
        f"---\n"
        f'title: "{_alias(s.title).replace(chr(34), chr(39))[:200]}"\n'
        f"category: {s.category or 'misc'}\n"
        f"tags: [{', '.join(s.tags)}]\n"
        f"source: {s.source}\n"
        f"url: {s.url}\n"
        f"score: {s.score:.2f}\n"
        f"{rline}"
        f"captured: {s.captured}\n"
        f"rating:\n"               # ← set 1-5 in Obsidian to teach CEREBRO what you value
        f"---\n"
        f"# {s.title}\n\n{rquote}{body}{dsec}\n\n[Open ↗]({s.url})\n"
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
        if p.exists() and _RATED.search(p.read_text(errors="replace")[:600]):
            continue                                  # preserve your rating
        p.write_text(_atomic(s))
    daily = daily_dir / f"{date}.md"
    daily.write_text(_daily(date, briefing, signals, stats))
    return {"daily": str(daily), "signals_dir": str(sig_dir), "n": len(signals)}
