from __future__ import annotations

from ..models import Signal
from .base import http_get, now_iso

# Port of Horizon's ossinsight scraper: api.ossinsight.io ranks repos by STARS GAINED in a
# window — true star-velocity, the clean complement to scraping github.com/trending. Same
# source="github" so a repo appearing in both dedups to one signal.
API = "https://api.ossinsight.io/v1/trends/repos/"


def fetch(cfg: dict, settings) -> list[Signal]:
    periods = cfg.get("period", "past_week")
    if isinstance(periods, str):
        periods = [periods]
    langs = cfg.get("languages") or ["All"]
    min_stars = cfg.get("min_stars", 0)
    out: list[Signal] = []
    seen: set[str] = set()
    for period in periods:
        for lang in langs:
            try:
                rows = http_get(API, params={"period": period, "language": lang}) \
                    .json().get("data", {}).get("rows", [])
            except Exception:  # noqa: BLE001
                continue
            for row in rows:
                repo = row.get("repo_name")
                if not repo or repo in seen:
                    continue
                stars = int(float(row.get("stars", 0) or 0))
                if stars < min_stars:
                    continue
                seen.add(repo)
                desc = (row.get("description") or "").strip()
                out.append(Signal(
                    url=f"https://github.com/{repo}",
                    title=f"{repo}: {desc}".strip().rstrip(":"), source="github",
                    captured=now_iso(),
                    meta={"repo": repo, "stars_gained": stars, "period": period,
                          "lang": row.get("language"), "ossinsight": True},
                ))
    out.sort(key=lambda s: s.meta.get("stars_gained", 0), reverse=True)
    return out[: cfg.get("max_items", 40)]
