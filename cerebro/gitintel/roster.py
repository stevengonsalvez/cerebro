from __future__ import annotations

import pathlib
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DEFAULT_PATH = ROOT / "config" / "cracked_devs.yaml"


@dataclass
class CrackedDev:
    name: str
    tier: int = 2
    x: str = ""
    github: str = ""
    blog: str = ""
    blog_feed: str = ""
    reddit: str = ""
    tags: list[str] = field(default_factory=list)
    why: str = ""
    added: str = ""
    discovered_via: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def slug(self) -> str:
        """Stable identity key: github login wins, else x handle, else name."""
        return (self.github or self.x or self.name).strip().lstrip("@").lower()


def load_roster(path: str | pathlib.Path | None = None) -> tuple[list[CrackedDev], dict]:
    """Load the roster. Missing/empty file -> ([], default wiring). Never raises on absence.

    Precedent for tolerant load: gitintel/watchlists.py:6-8.
    """
    p = pathlib.Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return [], {"enabled": False}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [], {"enabled": False}

    wiring = dict(data.get("wiring") or {})
    wiring.setdefault("enabled", True)
    defaults = dict(data.get("defaults") or {})

    devs: list[CrackedDev] = []
    for raw in data.get("devs") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue  # name is the only hard requirement
        merged = {**defaults, **raw}
        devs.append(CrackedDev(
            name=name,
            tier=int(merged.get("tier") or 2),
            x=_handle(merged.get("x")),
            github=_handle(merged.get("github")),
            blog=_text(merged.get("blog")),
            blog_feed=_text(merged.get("blog_feed")),
            reddit=_handle(merged.get("reddit")),
            tags=[str(t) for t in (merged.get("tags") or [])],
            why=_text(merged.get("why")),
            added=_text(merged.get("added")),
            discovered_via=_text(merged.get("discovered_via")),
            enabled=bool(merged.get("enabled", True)),
        ))
    return devs, wiring


def active(devs: list[CrackedDev], wiring: dict) -> list[CrackedDev]:
    max_tier = int(wiring.get("max_tier") or 99)
    return [d for d in devs if d.enabled and d.tier <= max_tier]


def apply_to_sources(sources: dict, devs: list[CrackedDev], wiring: dict) -> dict:
    """Fold roster handles into the raw sources dict. Mutates and returns `sources`.

    Existing `x` and `rss` adapters need no code change — they just see longer lists.
    """
    if not wiring.get("enabled"):
        return sources
    picked = active(devs, wiring)

    if wiring.get("feed_x", True):
        x_cfg = sources.setdefault("x", {})
        x_cfg["accounts"] = _merge_unique(x_cfg.get("accounts") or [], [d.x for d in picked if d.x])

    if wiring.get("feed_rss", True):
        rss_cfg = sources.setdefault("rss", {})
        rss_cfg["feeds"] = _merge_unique(
            rss_cfg.get("feeds") or [], [d.blog_feed for d in picked if d.blog_feed]
        )

    # New lanes read their targets from the injected config (adapters land in Phase 3/4).
    if wiring.get("feed_github", True):
        gh = sources.setdefault("github_devs", {"enabled": False})
        gh["logins"] = _merge_unique(gh.get("logins") or [], [d.github for d in picked if d.github])

    if wiring.get("feed_reddit", True):
        rd = sources.setdefault("reddit_users", {"enabled": False})
        rd["users"] = _merge_unique(rd.get("users") or [], [d.reddit for d in picked if d.reddit])

    return sources


def by_github(devs: list[CrackedDev]) -> dict[str, CrackedDev]:
    return {d.github.lower(): d for d in devs if d.github}


def _merge_unique(existing: list, extra: list) -> list:
    """Case-insensitive dedup, preserving original order and original casing."""
    seen = {str(v).strip().lower() for v in existing}
    out = list(existing)
    for v in extra:
        key = str(v).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _handle(v: Any) -> str:
    return str(v).strip().lstrip("@") if v else ""


def _text(v: Any) -> str:
    return str(v).strip() if v else ""
