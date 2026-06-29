from __future__ import annotations

import re
from collections import Counter

from .github_client import GitHubClient, GitHubClientError
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
    )


def inspect_profile(value: str, client: GitHubClient, repo_limit: int = 8) -> ProfileInspection:
    login = parse_login(value)
    data = client.get_user(login) or {}
    user = user_from_api(data or {"login": login, "html_url": f"https://github.com/{login}"}, "exact")
    repos = []
    langs = Counter()
    try:
        raw_repos = client.get_user_repos(login, limit=repo_limit * 2)
        ranked = sorted(
            [r for r in raw_repos if not r.get("archived")],
            key=lambda r: int(r.get("stargazers_count") or 0) + int(r.get("forks_count") or 0) * 2,
            reverse=True,
        )[:repo_limit]
        for raw in ranked:
            cand = inspect_repo(repo_from_api(raw, "profile"), client)
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
    )
