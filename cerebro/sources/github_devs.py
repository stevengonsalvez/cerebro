from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..gitintel.github_client import GitHubClient, GitHubClientError
from ..models import Signal
from .base import now_iso


def fetch(cfg: dict, settings) -> list[Signal]:
    logins = [str(x).strip().lstrip("@") for x in (cfg.get("logins") or []) if str(x).strip()]
    if not logins:
        return []

    per_dev = int(cfg.get("per_dev", 5))
    window_days = int(cfg.get("window_days", 14))
    min_stars = int(cfg.get("min_stars", 0))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    client = GitHubClient(settings)
    out: list[Signal] = []
    for login in logins:
        try:
            # fetch more than per_dev so fork/archived/stale filtering has headroom
            repos = client.get_user_repos(login, per_dev * 3)
        except GitHubClientError:
            continue

        kept = 0
        for r in repos:
            if kept >= per_dev:
                break
            if r.get("fork") or r.get("archived"):
                continue
            if int(r.get("stargazers_count") or 0) < min_stars:
                continue
            pushed = _parse(r.get("pushed_at"))
            if pushed is None or pushed < cutoff:
                continue

            full = r.get("full_name") or f"{login}/{r.get('name')}"
            desc = r.get("description") or ""
            out.append(Signal(
                url=r.get("html_url") or f"https://github.com/{full}",
                title=f"{full}: {desc}".strip().rstrip(":"),
                source="github",  # folds into per_source github bucket (orchestrator.py:34-35)
                captured=now_iso(),
                clean_text=desc[:2000],
                topic_tags=list(r.get("topics") or []),
                source_tags=["github/cracked-dev"],
                entity_tags=[f"developer/{login}", f"repo/{full}"],
                meta={
                    "dev": login,
                    "full_name": full,
                    "stars": r.get("stargazers_count") or 0,
                    "language": r.get("language") or "",
                    "pushed_at": r.get("pushed_at") or "",
                    "published": r.get("pushed_at") or "",
                },
            ))
            kept += 1
    return out


def _parse(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
