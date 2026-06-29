from __future__ import annotations

from ..gitintel.repo_search import search_github
from ..models import Signal
from .base import now_iso


def fetch(cfg: dict, settings) -> list[Signal]:
    out: list[Signal] = []
    queries = cfg.get("queries") or []
    target = cfg.get("target", "mixed")
    max_items = int(cfg.get("max_items", 20))
    per_query = max(1, max_items // max(len(queries), 1))
    for query in queries:
        result = search_github(query, settings=settings, target=target, limit=per_query, deep=False)
        for repo in result.get("repositories", []):
            entity_id = repo.get("full_name", "")
            if not entity_id:
                continue
            sig = Signal(
                url=repo.get("url") or f"https://github.com/{entity_id}",
                title=f"{entity_id}: {repo.get('description') or 'GitHub repository'}",
                source="github_search",
                captured=now_iso(),
                clean_text=repo.get("readme_excerpt", "") or repo.get("description", ""),
                source_tags=["github/search", "github/repo"],
                entity_tags=[f"repo/{entity_id}"],
                meta={
                    "entity_type": "repo",
                    "entity_id": entity_id,
                    "github_query": query,
                    "repo_meta": repo,
                    "reason": repo.get("reason", ""),
                    "stars": repo.get("stars"),
                    "language": repo.get("language"),
                },
            )
            sig.merge_tags()
            out.append(sig)
        for user in result.get("users", []):
            login = user.get("login", "")
            if not login:
                continue
            sig = Signal(
                url=user.get("url") or f"https://github.com/{login}",
                title=f"@{login}: {user.get('bio') or user.get('name') or 'GitHub profile'}",
                source="github_search",
                captured=now_iso(),
                clean_text=user.get("bio", ""),
                source_tags=["github/search", "github/user"],
                entity_tags=[f"developer/{login}"],
                meta={
                    "entity_type": "developer",
                    "entity_id": login,
                    "github_query": query,
                    "user_meta": user,
                    "reason": user.get("reason", ""),
                },
            )
            sig.merge_tags()
            out.append(sig)
    return out[:max_items]
