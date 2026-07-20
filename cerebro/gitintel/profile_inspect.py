from __future__ import annotations

import re
from collections import Counter

from .github_client import GitHubClient, GitHubClientError
from .metrics import enrich_repo_metrics, enrich_user_metrics, portfolio_momentum
from .models import GitHubRepoCandidate, GitHubUserCandidate, ProfileInspection
from .repo_inspect import inspect_repo, repo_from_api


def parse_login(value: str) -> str:
    text = value.strip()
    text = text.removeprefix("@")
    m = re.search(r"github\.com/([^/?#]+)", text)
    if m:
        return m.group(1)
    return text.strip("/")


def user_from_api(data: dict, track: str = "semantic") -> GitHubUserCandidate:
    return GitHubUserCandidate(
        login=data.get("login", ""),
        url=data.get("html_url", ""),
        name=data.get("name") or "",
        bio=data.get("bio") or "",
        followers=int(data.get("followers") or 0),
        public_repos=int(data.get("public_repos") or 0),
        track=track,
        blog=_clean_url(data.get("blog")),
        twitter_username=(data.get("twitter_username") or "").strip().lstrip("@"),
        company=(data.get("company") or "").strip(),
        location=(data.get("location") or "").strip(),
    )


def _clean_url(v) -> str:
    """GitHub `blog` is user-typed: often bare-domain, sometimes empty, sometimes junk."""
    s = (v or "").strip()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    return s


def inspect_profile(value: str, client: GitHubClient, repo_limit: int = 8) -> ProfileInspection:
    login = parse_login(value)
    data = client.get_user(login) or {}
    user = user_from_api(data or {"login": login, "html_url": f"https://github.com/{login}"}, "exact")
    enrich_user_metrics(user, client.cache)
    repos = []
    langs = Counter()
    try:
        raw_repos = client.get_user_repos(login, limit=repo_limit * 2)
        candidates = [
            enrich_repo_metrics(repo_from_api(raw, "profile"), client.cache)
            for raw in raw_repos
            if not raw.get("archived")
        ]
        ranked = sorted(
            candidates,
            key=lambda r: (
                r.momentum_score,
                int(r.stars or 0) + int(r.forks or 0) * 2,
            ),
            reverse=True,
        )[:repo_limit]
        for cand in ranked:
            cand = enrich_repo_metrics(inspect_repo(cand, client), client.cache)
            repos.append(cand)
            if cand.language:
                langs[cand.language] += 1
    except GitHubClientError:
        pass
    readme = ""
    try:
        readme = client.get_readme(login, login)
    except GitHubClientError:
        readme = ""
    return ProfileInspection(
        login=login,
        url=user.url or f"https://github.com/{login}",
        name=user.name,
        bio=user.bio,
        followers=user.followers,
        public_repos=user.public_repos,
        readme_excerpt=" ".join(readme[:4000].split()),
        repos=repos,
        primary_languages=[name for name, _ in langs.most_common(5)],
        followers_gained_7d=user.followers_gained_7d,
        followers_gained_30d=user.followers_gained_30d,
        growth_score=user.growth_score,
        portfolio_momentum_score=portfolio_momentum(repos),
        momentum_score=max(user.momentum_score, portfolio_momentum(repos)),
        growth_reason=user.growth_reason,
        blog=user.blog,
        twitter_username=user.twitter_username,
        company=user.company,
        location=user.location,
    )
