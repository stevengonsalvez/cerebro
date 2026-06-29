from __future__ import annotations

from cerebro.gitintel.github_client import GitHubClient
from cerebro.gitintel.query_plan import plan_query
from cerebro.gitintel.repo_search import search_github


class Settings:
    github = {"cache_path": ":memory:", "cache_ttl_hours": 24, "request_timeout_seconds": 3, "token_env": "NO_TOKEN"}


def test_query_plan_preserves_exact_owner_repo_and_rare_token():
    plan = plan_query('tools that turn "github profile" into cursor skill filiksyos/gittoskill')

    assert "github profile" in plan.exact_terms
    assert "filiksyos/gittoskill" in plan.exact_terms
    assert "filiksyos/gittoskill" in plan.must_keep
    assert "cursor" in plan.semantic_terms


def test_search_github_returns_gittoskill(monkeypatch):
    def fake_search_repositories(self, query, limit=10):
        return {
            "total_count": 1,
            "items": [{
                "full_name": "filiksyos/gittoskill",
                "html_url": "https://github.com/filiksyos/gittoskill",
                "description": "GitHub Profile into skill",
                "stargazers_count": 60,
                "forks_count": 11,
                "open_issues_count": 1,
                "updated_at": "2026-06-29T00:00:00Z",
                "pushed_at": "2026-06-27T00:00:00Z",
                "language": "TypeScript",
                "topics": ["skills", "github"],
            }],
        }

    monkeypatch.setattr(GitHubClient, "search_repositories", fake_search_repositories)
    monkeypatch.setattr(GitHubClient, "search_users", lambda self, query, limit=10: {"total_count": 0, "items": []})
    monkeypatch.setattr(GitHubClient, "get_repo", lambda self, owner, repo: None)
    monkeypatch.setattr(GitHubClient, "get_readme", lambda self, owner, repo: "Generate coding skills from GitHub profiles.")
    monkeypatch.setattr(GitHubClient, "get_languages", lambda self, owner, repo: {"TypeScript": 100})
    monkeypatch.setattr(GitHubClient, "get_topics", lambda self, owner, repo: ["skills", "github"])
    monkeypatch.setattr(GitHubClient, "get_repo_contents", lambda self, owner, repo, path="": [{"name": "README.md"}])

    result = search_github("gittoskill", settings=Settings(), limit=5)

    assert result["repositories"][0]["full_name"] == "filiksyos/gittoskill"
    assert "exact_terms" in result["query_plan"]
    assert result["repositories"][0]["reason"]
