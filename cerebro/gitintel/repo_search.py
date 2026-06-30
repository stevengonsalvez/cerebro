from __future__ import annotations

import time

from .github_client import GitHubClient, GitHubClientError
from .models import GitHubRepoCandidate, SearchResult
from .profile_inspect import user_from_api
from .query_plan import extract_owner_repos, plan_query
from .rank import rank_repositories, rank_users
from .repo_inspect import inspect_repo, repo_from_api


def _dedupe_repos(candidates: list[GitHubRepoCandidate]) -> list[GitHubRepoCandidate]:
    out = {}
    for cand in candidates:
        if not cand.full_name:
            continue
        existing = out.get(cand.full_name.lower())
        if not existing or cand.track == "exact":
            out[cand.full_name.lower()] = cand
    return list(out.values())


def search_github(query: str, settings=None, target: str = "mixed", limit: int = 10, deep: bool = False) -> dict:
    started = time.monotonic()
    client = GitHubClient(settings)
    plan = plan_query(query, target)
    stages: list[dict] = [{"stage": "query_plan", "plan": plan.to_dict()}]
    repos: list[GitHubRepoCandidate] = []
    users = []
    total_count = 0
    errors = []

    if target in ("mixed", "repositories", "repos"):
        for owner_repo in extract_owner_repos(query):
            owner, repo = owner_repo.split("/", 1)
            try:
                data = client.get_repo(owner, repo)
                if data:
                    repos.append(repo_from_api(data, "exact"))
                    stages.append({"stage": "exact_lookup", "entity": owner_repo, "ok": True})
            except GitHubClientError as exc:
                errors.append(str(exc))
                stages.append({"stage": "exact_lookup", "entity": owner_repo, "ok": False, "error": str(exc)})
        for q in plan.github_queries:
            try:
                data = client.search_repositories(q, limit=limit)
                total_count += int(data.get("total_count") or 0)
                for item in data.get("items", [])[:limit]:
                    repos.append(repo_from_api(item, "exact" if q in plan.exact_terms else "semantic"))
                stages.append({"stage": "github_search", "target": "repositories", "query": q, "count": len(data.get("items", []))})
            except GitHubClientError as exc:
                errors.append(str(exc))
                stages.append({"stage": "github_search", "target": "repositories", "query": q, "error": str(exc)})

    if target in ("mixed", "users"):
        for q in plan.github_queries[:2]:
            try:
                data = client.search_users(q, limit=min(limit, 10))
                total_count += int(data.get("total_count") or 0)
                for item in data.get("items", [])[: min(limit, 10)]:
                    login = item.get("login", "")
                    try:
                        full = client.get_user(login) if login else item
                    except GitHubClientError:
                        full = item
                    users.append(user_from_api(full or item, "semantic"))
                stages.append({"stage": "github_search", "target": "users", "query": q, "count": len(data.get("items", []))})
            except GitHubClientError as exc:
                errors.append(str(exc))
                stages.append({"stage": "github_search", "target": "users", "query": q, "error": str(exc)})

    repos = _dedupe_repos(repos)
    enrich_top = min(limit if deep else min(limit, 5), len(repos))
    enriched = []
    for cand in repos[:enrich_top]:
        enriched.append(inspect_repo(cand, client))
    repos = enriched + repos[enrich_top:]
    stages.append({"stage": "repo_inspection", "count": len(enriched)})

    ranked_repos = rank_repositories(repos, plan)[:limit]
    ranked_users = rank_users(users, plan)[:limit]
    stages.append({"stage": "ranking", "repositories": len(ranked_repos), "users": len(ranked_users)})

    result = SearchResult(
        input_query=query,
        query_plan=plan,
        repositories=ranked_repos,
        users=ranked_users,
        total_count=total_count,
        response_time_ms=int((time.monotonic() - started) * 1000),
        retry_info={"success_on_retry": False, "retry_attempts": 0, "word_actions": []},
        rate_limit=client.rate_limit,
        stages=stages + ([{"stage": "errors", "errors": errors}] if errors else []) + [{"stage": "result"}],
    )
    return result.to_dict()
