from __future__ import annotations

import re

from .models import SearchPlan

OWNER_REPO = re.compile(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b")
GITHUB_REPO_URL = re.compile(
    r"\b(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:[/?#\s]|$)"
)
TOKEN = re.compile(r"[A-Za-z0-9_.-]+")
STOP = {
    "a", "an", "and", "are", "being", "for", "from", "in", "into", "of", "on",
    "or", "that", "the", "this", "to", "tools", "turn", "with",
}
GITHUBISH = {"github", "repo", "repos", "repository", "cli", "skill", "agent", "cursor", "claude", "code"}


def plan_query(query: str, target: str = "mixed") -> SearchPlan:
    quoted = re.findall(r'"([^"]+)"', query)
    owner_repos = extract_owner_repos(query)
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


def extract_owner_repos(query: str) -> list[str]:
    repos = []
    consumed: list[tuple[int, int]] = []
    for match in GITHUB_REPO_URL.finditer(query):
        repos.append(_clean_owner_repo(match.group(1)))
        consumed.append(match.span())

    scrubbed = list(query)
    for start, end in consumed:
        scrubbed[start:end] = " " * (end - start)
    for owner_repo in OWNER_REPO.findall("".join(scrubbed)):
        repos.append(_clean_owner_repo(owner_repo))
    return list(dict.fromkeys(repo for repo in repos if repo))


def _clean_owner_repo(value: str) -> str:
    owner_repo = value.strip().removesuffix(".git").strip("/")
    parts = owner_repo.split("/", 1)
    if len(parts) != 2 or parts[0].lower() == "github.com":
        return ""
    return owner_repo
