from __future__ import annotations

from ..models import Signal


def _alias(title: str) -> str:
    return title.replace("|", " ").replace("[", "(").replace("]", ")")


def _atomic(s: Signal) -> str:
    body = (s.clean_text[:600].strip() or s.title)
    return (
        f"---\n"
        f"category: {s.category or 'misc'}\n"
        f"tags: [{', '.join(s.tags)}]\n"
        f"source: {s.source}\n"
        f"url: {s.url}\n"
        f"score: {s.score:.2f}\n"
        f"captured: {s.captured}\n"
        f"---\n"
        f"# {s.title}\n\n{body}\n\n[Open ↗]({s.url})\n"
    )


def _daily(date: str, briefing: str, signals: list[Signal]) -> str:
    index = "\n".join(
        f"- [[{s.url_hash}|{_alias(s.title)}]] · {s.source} · {s.score:.2f}"
        for s in signals
    )
    return (
        f"---\ndate: {date}\ntype: cerebro-briefing\ncount: {len(signals)}\n---\n"
        f"# CEREBRO — {date}\n\n{briefing}\n\n## Signals\n{index}\n"
    )


def write(date: str, briefing: str, signals: list[Signal], settings) -> dict:
    """Daily briefing note + one atomic note per signal. Dry-run → _scratch/.
    Idempotent: atomic filenames are the url_hash; the daily note overwrites."""
    root = (settings.vault_path / "_scratch") if settings.dry_run else settings.vault_path
    daily_dir, sig_dir = root / "Daily", root / "Signals"
    daily_dir.mkdir(parents=True, exist_ok=True)
    sig_dir.mkdir(parents=True, exist_ok=True)
    for s in signals:
        (sig_dir / f"{s.url_hash}.md").write_text(_atomic(s))
    daily = daily_dir / f"{date}.md"
    daily.write_text(_daily(date, briefing, signals))
    return {"daily": str(daily), "signals_dir": str(sig_dir), "n": len(signals)}
