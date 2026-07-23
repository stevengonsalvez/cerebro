from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from .metrics import enrich_repo_metrics, enrich_user_metrics, portfolio_momentum
from .profile_inspect import user_from_api
from .repo_inspect import repo_from_api

# Weighting across the four crackedness signals. Cheap signals (follower,
# portfolio, ships) sum to 0.65; the deep commit-rate pass owns the rest.
# Both stages score on ONE full-scale [0,1] axis: cheap treats the unknown
# commit signal as 0 (so cheap maxes at 0.65), deep replaces that 0 with the
# real commit rate. This keeps a single admission threshold consistent —
# deep-scoring can only ever raise a score, never demote a strong candidate
# below a weaker un-deep-scored one.
WEIGHTS = {"commit": 0.35, "follower": 0.25, "portfolio": 0.25, "ships": 0.15}


@dataclass
class CrackScore:
    login: str
    score: float
    commits_per_day: float = 0.0
    followers_gained_30d: int = 0
    portfolio_momentum: float = 0.0
    ships_score: float = 0.0
    deep: bool = False
    reason: str = ""


def cheap_score(login: str, client, cache, *, captured_at: str | None = None) -> CrackScore:
    """Stage A: no events call. Follower growth + portfolio momentum + ships-a-lot,
    renormalised over the three cheap weights. Deterministic given captured_at."""
    ref = _parse_iso(captured_at) or _now()
    data = client.get_user(login) or {"login": login, "html_url": f"https://github.com/{login}"}
    user = user_from_api(data)
    enrich_user_metrics(user, cache, captured_at=captured_at, record=False)
    follower_sig = user.growth_score

    raw_repos = client.get_user_repos(login, limit=40) or []
    repos = [
        enrich_repo_metrics(repo_from_api(raw, "crack"), cache, captured_at=captured_at, record=False)
        for raw in raw_repos
        if not raw.get("archived")
    ]
    portfolio_sig = portfolio_momentum(repos)
    ships_sig = _ships_score(data, raw_repos, ref)

    # Full-scale: commit signal unknown at Stage A -> contributes 0 (max cheap = 0.65).
    score = round(
        follower_sig * WEIGHTS["follower"]
        + portfolio_sig * WEIGHTS["portfolio"]
        + ships_sig * WEIGHTS["ships"],
        4,
    )
    return CrackScore(
        login=login,
        score=score,
        followers_gained_30d=user.followers_gained_30d or 0,
        portfolio_momentum=portfolio_sig,
        ships_score=ships_sig,
        deep=False,
        reason=f"cheap: follower {follower_sig:.2f}, portfolio {portfolio_sig:.2f}, ships {ships_sig:.2f}",
    )


def deep_score(base: CrackScore, client, *, window_days: int = 90, now: str | None = None) -> CrackScore:
    """Stage B: add commit-rate/day from PushEvents in window, weight 0.35, recombine.
    Deterministic given `now`; commits outside the window are ignored."""
    ref = _parse_iso(now) or _now()
    cutoff = ref - dt.timedelta(days=window_days)
    events = client.request(f"/users/{base.login}/events", {"per_page": 100}) or []
    commits = 0
    for e in events:
        if (e.get("type") or "") != "PushEvent":
            continue
        created = _parse_iso(e.get("created_at"))
        if created is None or created < cutoff or created > ref:
            continue
        payload = e.get("payload") or {}
        # /users/{login}/events returns ABBREVIATED PushEvent payloads
        # (keys: before/head/push_id/ref/repository_id) — no "size", no
        # "commits" array. Fall back to 1 commit per push so an active
        # pusher never scores 0; use size/commits when the event carries them.
        size = payload.get("size")
        if size is None:
            size = len(payload.get("commits") or []) or 1
        commits += int(size or 0)

    commits_per_day = commits / window_days if window_days else 0.0
    # ponytail: linear cap at 5 commits/day = maxed signal; tune cap if calibration drifts
    commit_sig = min(commits_per_day / 5.0, 1.0)
    # base.score already carries the cheap signals on the full scale (commit=0);
    # just add the now-known commit contribution.
    score = round(base.score + commit_sig * WEIGHTS["commit"], 4)
    return CrackScore(
        login=base.login,
        score=score,
        commits_per_day=round(commits_per_day, 4),
        followers_gained_30d=base.followers_gained_30d,
        portfolio_momentum=base.portfolio_momentum,
        ships_score=base.ships_score,
        deep=True,
        reason=f"{base.reason}; commit {commit_sig:.2f} ({commits_per_day:.2f}/day)",
    )


def _ships_score(data: dict, raw_repos: list[dict], ref: dt.datetime) -> float:
    """min(log10(repos+1)/2,1)*0.5 + push_recency*0.3 + young_high_output*0.2."""
    public_repos = int(data.get("public_repos") or len(raw_repos) or 0)
    volume = min(math.log10(public_repos + 1) / 2, 1.0)

    pushes = [_parse_iso(r.get("pushed_at")) for r in raw_repos]
    last_push = max((p for p in pushes if p is not None), default=None)
    if last_push is None:
        recency = 0.0
    else:
        days = max((ref - last_push).days, 0)
        recency = max(0.0, 1.0 - days / 30.0)

    created = _parse_iso(data.get("created_at"))
    if created is None or public_repos <= 0:
        young_high_output = 0.0
    else:
        age_years = max((ref - created).days / 365.0, 0.5)
        # ponytail: repos-per-year, 20/yr = maxed; young accounts score higher (smaller denom)
        young_high_output = min((public_repos / age_years) / 20.0, 1.0)

    return round(volume * 0.5 + recency * 0.3 + young_high_output * 0.2, 4)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)
