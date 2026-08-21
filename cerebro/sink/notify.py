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


def push_failure(message: str, settings) -> None:
    """Alert for failures AFTER the briefing was written — the vault push, the deploy
    hook, the roundup. push() fires from orchestrator.py, before run.sh reaches
    `git push`, so every one of those failures is currently silent. NOT muted by
    dry_run: a run that dies is news whether or not it was writing for real."""
    topic = getattr(settings, "ntfy_topic", "")
    if not topic:
        return
    try:
        subprocess.run(
            ["curl", "-fsS", "-H", "Title: CEREBRO FAILED", "-H", "Priority: high",
             "-d", message[:400], f"https://ntfy.sh/{topic}"],
            timeout=15, capture_output=True,
        )
    except Exception:
        pass  # alerting is best-effort; never turn a failure into a second failure
