from __future__ import annotations

import subprocess


def push(stats, daily_path: str, settings) -> None:
    """ntfy push via curl. No-op in dry-run or when no topic is set."""
    if settings.dry_run or not settings.ntfy_topic:
        return
    msg = f"briefing ready · {stats.digested} signals"
    try:
        subprocess.run(
            ["curl", "-fsS", "-H", "Title: CEREBRO", "-d", msg,
             f"https://ntfy.sh/{settings.ntfy_topic}"],
            timeout=15, capture_output=True,
        )
    except Exception:
        pass  # notification is best-effort; never fail the run on it
