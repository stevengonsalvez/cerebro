from __future__ import annotations

from cerebro.gitintel.cache import GitIntelCache
from cerebro.gitintel.github_client import GitHubClient
from cerebro.gitintel.metrics import enrich_repo_metrics, enrich_user_metrics
from cerebro.gitintel.models import GitHubRepoCandidate, GitHubUserCandidate, SearchPlan
from cerebro.gitintel.profile_inspect import inspect_profile
from cerebro.gitintel.rank import rank_repositories, rank_users


class Settings:
    github = {"cache_path": ":memory:", "cache_ttl_hours": 24, "request_timeout_seconds": 3, "token_env": "NO_TOKEN"}


NOW = "2026-06-30T00:00:00+00:00"
WEEK_AGO = "2026-06-22T00:00:00+00:00"
MONTH_AGO = "2026-05-30T00:00:00+00:00"


def test_repo_momentum_can_outrank_static_stars() -> None:
    cache = GitIntelCache(":memory:")
    cache.record_repo_metrics("famous/stale", stars=100_000, captured_at=WEEK_AGO)
    cache.record_repo_metrics("famous/stale", stars=99_900, captured_at=MONTH_AGO)
    cache.record_repo_metrics("new/hot", stars=100, captured_at=WEEK_AGO)
    cache.record_repo_metrics("new/hot", stars=80, captured_at=MONTH_AGO)

    famous = enrich_repo_metrics(
        GitHubRepoCandidate(
            full_name="famous/stale",
            url="https://github.com/famous/stale",
            description="agent runtime",
            stars=100_020,
            pushed_at=NOW,
        ),
        cache,
        captured_at=NOW,
        record=False,
    )
    hot = enrich_repo_metrics(
        GitHubRepoCandidate(
            full_name="new/hot",
            url="https://github.com/new/hot",
            description="agent runtime",
            stars=600,
            pushed_at=NOW,
        ),
        cache,
        captured_at=NOW,
        record=False,
    )

    ranked = rank_repositories([famous, hot], SearchPlan(input_query="agent", semantic_terms=["agent"]))

    assert ranked[0].full_name == "new/hot"
    assert hot.stars_gained_7d == 500
    assert famous.stars_gained_7d == 20
    assert "+500 stars/7d" in hot.reason


def test_user_momentum_can_outrank_static_followers() -> None:
    cache = GitIntelCache(":memory:")
    cache.record_developer_metrics("famous", followers=100_000, captured_at=WEEK_AGO)
    cache.record_developer_metrics("newbuilder", followers=100, captured_at=WEEK_AGO)

    famous = enrich_user_metrics(
        GitHubUserCandidate(
            login="famous",
            url="https://github.com/famous",
            bio="agent runtime",
            followers=100_010,
        ),
        cache,
        captured_at=NOW,
        record=False,
    )
    builder = enrich_user_metrics(
        GitHubUserCandidate(
            login="newbuilder",
            url="https://github.com/newbuilder",
            bio="agent runtime",
            followers=320,
        ),
        cache,
        captured_at=NOW,
        record=False,
    )

    ranked = rank_users([famous, builder], SearchPlan(input_query="agent", semantic_terms=["agent"]))

    assert ranked[0].login == "newbuilder"
    assert builder.followers_gained_7d == 220
    assert "+220 followers/7d" in builder.reason


def test_profile_inspection_orders_owned_repos_by_momentum(monkeypatch) -> None:
    cache = GitIntelCache(":memory:")
    cache.record_repo_metrics("builder/famous", stars=50_000, captured_at=WEEK_AGO)
    cache.record_repo_metrics("builder/hot", stars=50, captured_at=WEEK_AGO)
    client = GitHubClient(Settings(), cache=cache)

    monkeypatch.setattr(
        client,
        "get_user",
        lambda login: {
            "login": login,
            "html_url": f"https://github.com/{login}",
            "bio": "agent builder",
            "followers": 100,
            "public_repos": 2,
        },
    )
    monkeypatch.setattr(
        client,
        "get_user_repos",
        lambda login, limit=20: [
            {
                "full_name": "builder/famous",
                "html_url": "https://github.com/builder/famous",
                "description": "agent runtime",
                "stargazers_count": 50_010,
                "forks_count": 1000,
                "archived": False,
            },
            {
                "full_name": "builder/hot",
                "html_url": "https://github.com/builder/hot",
                "description": "agent runtime",
                "stargazers_count": 550,
                "forks_count": 10,
                "archived": False,
            },
        ],
    )
    monkeypatch.setattr(client, "get_repo", lambda owner, repo: None)
    monkeypatch.setattr(client, "get_readme", lambda owner, repo: "")
    monkeypatch.setattr(client, "get_languages", lambda owner, repo: {})
    monkeypatch.setattr(client, "get_topics", lambda owner, repo: [])
    monkeypatch.setattr(client, "get_repo_contents", lambda owner, repo, path="": [])

    profile = inspect_profile("builder", client, repo_limit=2)

    assert [repo.full_name for repo in profile.repos] == ["builder/hot", "builder/famous"]
    assert profile.portfolio_momentum_score > 0
