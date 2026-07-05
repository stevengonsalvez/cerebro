from __future__ import annotations

import datetime as dt
import math
from typing import Any

from .cache import GitIntelCache
from .models import GitHubRepoCandidate, GitHubUserCandidate


def enrich_repo_metrics(
    candidate: GitHubRepoCandidate,
    cache: GitIntelCache,
    *,
    captured_at: str | None = None,
    record: bool = True,
) -> GitHubRepoCandidate:
    captured = _parse_time(captured_at) if captured_at else _now()
    snapshots = cache.repo_metric_snapshots(candidate.full_name)
    metrics = _growth_metrics(
        snapshots,
        captured,
        current_value=max(candidate.stars, 0),
        value_key="stars",
    )
    candidate.stars_gained_7d = metrics["gained_7d"]
    candidate.stars_gained_30d = metrics["gained_30d"]
    candidate.growth_score = metrics["growth_score"]
    candidate.momentum_score = metrics["momentum_score"]
    candidate.growth_reason = _repo_growth_reason(candidate)
    if record:
        cache.record_repo_metrics(
            candidate.full_name,
            stars=max(candidate.stars, 0),
            forks=max(candidate.forks, 0),
            captured_at=captured.isoformat(),
        )
    return candidate


def enrich_user_metrics(
    candidate: GitHubUserCandidate,
    cache: GitIntelCache,
    *,
    captured_at: str | None = None,
    record: bool = True,
) -> GitHubUserCandidate:
    captured = _parse_time(captured_at) if captured_at else _now()
    snapshots = cache.developer_metric_snapshots(candidate.login)
    metrics = _growth_metrics(
        snapshots,
        captured,
        current_value=max(candidate.followers, 0),
        value_key="followers",
    )
    candidate.followers_gained_7d = metrics["gained_7d"]
    candidate.followers_gained_30d = metrics["gained_30d"]
    candidate.growth_score = metrics["growth_score"]
    candidate.momentum_score = max(candidate.momentum_score, metrics["momentum_score"])
    candidate.growth_reason = _user_growth_reason(candidate)
    if record:
        cache.record_developer_metrics(
            candidate.login,
            followers=max(candidate.followers, 0),
            public_repos=max(candidate.public_repos, 0),
            captured_at=captured.isoformat(),
        )
    return candidate


def portfolio_momentum(repos: list[GitHubRepoCandidate]) -> float:
    scores = sorted((repo.momentum_score for repo in repos), reverse=True)
    if not scores:
        return 0.0
    best = scores[0]
    top3 = sum(scores[:3]) / min(len(scores), 3)
    return round(min(best * 0.6 + top3 * 0.4, 1.0), 4)


def _growth_metrics(
    snapshots: list[dict[str, Any]],
    captured: dt.datetime,
    *,
    current_value: int,
    value_key: str,
) -> dict[str, float | int | None]:
    previous_7d = _snapshot_at_or_before(snapshots, captured - dt.timedelta(days=7))
    previous_30d = _snapshot_at_or_before(snapshots, captured - dt.timedelta(days=30))
    gained_7d = _gain(current_value, previous_7d, value_key)
    gained_30d = _gain(current_value, previous_30d, value_key)
    growth_score = _growth_score(current_value, gained_7d, gained_30d)
    momentum_score = _momentum_score(gained_7d, gained_30d, growth_score)
    return {
        "gained_7d": gained_7d,
        "gained_30d": gained_30d,
        "growth_score": growth_score,
        "momentum_score": momentum_score,
    }


def _snapshot_at_or_before(snapshots: list[dict[str, Any]], cutoff: dt.datetime) -> dict[str, Any] | None:
    chosen = None
    for snapshot in snapshots:
        captured_at = _parse_time(str(snapshot.get("captured_at", "")))
        if captured_at <= cutoff:
            chosen = snapshot
        else:
            break
    return chosen


def _gain(current_value: int, snapshot: dict[str, Any] | None, value_key: str) -> int | None:
    if not snapshot:
        return None
    try:
        return max(current_value - int(snapshot.get(value_key, 0) or 0), 0)
    except (TypeError, ValueError):
        return None


def _growth_score(current_value: int, gained_7d: int | None, gained_30d: int | None) -> float:
    if gained_7d is None and gained_30d is None:
        return 0.0
    gain7 = gained_7d or 0
    gain30 = gained_30d or gain7
    previous = max(current_value - gain7, 50)
    pct_growth = min(gain7 / previous, 1.0)
    log_gain = min(math.log10(gain7 + 1) / 3, 1.0)
    velocity7 = gain7 / 7
    velocity30 = gain30 / 30 if gain30 else 0
    acceleration = velocity7 / max(velocity30, 1)
    acceleration_score = min(math.log2(max(acceleration, 1)) / 3, 1.0)
    return round(log_gain * 0.4 + pct_growth * 0.3 + acceleration_score * 0.3, 4)


def _momentum_score(gained_7d: int | None, gained_30d: int | None, growth_score: float) -> float:
    gain7 = gained_7d or 0
    gain30 = gained_30d or gain7
    recency = 0.0 if gain30 <= 0 else min(gain7 / max(gain30, 1), 1.0)
    return round(min(growth_score * 0.75 + recency * 0.25, 1.0), 4)


def _repo_growth_reason(candidate: GitHubRepoCandidate) -> str:
    parts = []
    if candidate.stars_gained_7d is not None:
        parts.append(f"+{candidate.stars_gained_7d} stars/7d")
    if candidate.stars_gained_30d is not None:
        parts.append(f"+{candidate.stars_gained_30d} stars/30d")
    return "; ".join(parts)


def _user_growth_reason(candidate: GitHubUserCandidate) -> str:
    parts = []
    if candidate.followers_gained_7d is not None:
        parts.append(f"+{candidate.followers_gained_7d} followers/7d")
    if candidate.followers_gained_30d is not None:
        parts.append(f"+{candidate.followers_gained_30d} followers/30d")
    return "; ".join(parts)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _parse_time(value: str) -> dt.datetime:
    if not value:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)
