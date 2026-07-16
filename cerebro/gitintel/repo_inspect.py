from __future__ import annotations

from .github_client import GitHubClient, GitHubClientError
from .models import GitHubRepoCandidate, RepoInspection

MAX_TEXT = 6000
SELECTED = {"package.json", "pyproject.toml", "tsconfig.json", "tailwind.config.ts", "tailwind.config.js", "AGENTS.md", "CLAUDE.md"}


def _owner_repo(full_name: str) -> tuple[str, str]:
    owner, repo = full_name.split("/", 1)
    return owner, repo


def repo_from_api(data: dict, track: str = "semantic") -> GitHubRepoCandidate:
    return GitHubRepoCandidate(
        full_name=data.get("full_name", ""),
        url=data.get("html_url", ""),
        description=data.get("description") or "",
        stars=int(data.get("stargazers_count") or 0),
        forks=int(data.get("forks_count") or 0),
        open_issues=int(data.get("open_issues_count") or 0),
        updated_at=data.get("updated_at") or "",
        pushed_at=data.get("pushed_at") or "",
        language=data.get("language") or "",
        topics=list(data.get("topics") or []),
        track=track,
    )


def inspect_repo(candidate: GitHubRepoCandidate, client: GitHubClient) -> GitHubRepoCandidate:
    if not candidate.full_name or "/" not in candidate.full_name:
        return candidate
    owner, repo = _owner_repo(candidate.full_name)
    try:
        repo_data = client.get_repo(owner, repo) or {}
        if repo_data:
            richer = repo_from_api(repo_data, candidate.track)
            candidate.description = candidate.description or richer.description
            candidate.stars = richer.stars or candidate.stars
            candidate.forks = richer.forks or candidate.forks
            candidate.open_issues = richer.open_issues or candidate.open_issues
            candidate.updated_at = richer.updated_at or candidate.updated_at
            candidate.pushed_at = richer.pushed_at or candidate.pushed_at
            candidate.language = richer.language or candidate.language
            candidate.topics = sorted(set(candidate.topics + richer.topics))
        readme = client.get_readme(owner, repo)
        candidate.readme_excerpt = " ".join(readme[:MAX_TEXT].split())
        languages = client.get_languages(owner, repo)
        if languages and not candidate.language:
            candidate.language = max(languages, key=languages.get)
        topics = client.get_topics(owner, repo)
        candidate.topics = sorted(set(candidate.topics + topics))
        root = client.get_repo_contents(owner, repo)
        candidate.root_entries = [item.get("name", "") for item in root if item.get("name")]
    except GitHubClientError as exc:
        candidate.reason = f"Inspection partial: {exc}"
    return candidate


def inspect_repo_detail(full_name: str, client: GitHubClient) -> RepoInspection:
    candidate = inspect_repo(GitHubRepoCandidate(full_name=full_name, url=f"https://github.com/{full_name}"), client)
    owner, repo = _owner_repo(full_name)
    selected_files = {}
    try:
        for item in client.get_repo_contents(owner, repo):
            name = item.get("name", "")
            if name in SELECTED and item.get("download_url"):
                # Use API URLs only through the client cache/request path where possible.
                selected_files[name] = name
    except GitHubClientError:
        pass
    return RepoInspection(
        full_name=full_name,
        readme_excerpt=candidate.readme_excerpt,
        languages={candidate.language: 1} if candidate.language else {},
        topics=candidate.topics,
        root_entries=candidate.root_entries,
        selected_files=selected_files,
    )
