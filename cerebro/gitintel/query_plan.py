from __future__ import annotations

import re

from .models import SearchPlan

OWNER_REPO = re.compile(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b")
TOKEN = re.compile(r"[A-Za-z0-9_.-]+")
STOP = {
    "a", "an", "and", "are", "being", "for", "from", "in", "into", "of", "on",
    "or", "that", "the", "this", "to", "tools", "turn", "with",
}
GITHUBISH = {"github", "repo", "repos", "repository", "cli", "skill", "agent", "cursor", "claude", "code"}


def plan_query(query: str, target: str = "mixed") -> SearchPlan:
    quoted = re.findall(r'"([^"]+)"', query)
    owner_repos = OWNER_REPO.findall(query)
    raw = TOKEN.findall(query)
    tokens = [t.lower() for t in raw if t.lower() not in STOP]
    exact = []
    exact.extend(quoted)
    exact.extend(owner_repos)
    for token in raw:
        lower = token.lower()
        if "/" in token or len(token) >= 9 or "-" in token or "_" in token:
            if lower not in STOP:
                exact.append(token.strip())
    semantic = []
    for token in tokens:
        normalized = token.replace("_", "-")
        if normalized not in semantic:
            semantic.append(normalized)
    if not any(t in semantic for t in GITHUBISH):
        semantic.append("github")
    github_queries = []
    if semantic:
        github_queries.append(" ".join(semantic))
    if "skill" in semantic:
        if "profile" in semantic:
            github_queries.append("github profile skill")
            github_queries.append("profile skill")
        if "cursor" in semantic:
            github_queries.append("cursor skill")
        if "agent" in semantic:
            github_queries.append("agent skill")
    for term in exact:
        if term and term not in github_queries:
            github_queries.append(term)
    github_queries = list(dict.fromkeys(github_queries))[:5]
    return SearchPlan(
        input_query=query,
        target=target,
        exact_terms=list(dict.fromkeys(exact)),
        semantic_terms=semantic,
        must_keep=list(dict.fromkeys(exact)),
        github_queries=github_queries,
    )
