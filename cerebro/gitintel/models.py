from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GitHubRepoCandidate:
    full_name: str
    url: str
    description: str = ""
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    updated_at: str = ""
    pushed_at: str = ""
    language: str = ""
    topics: list[str] = field(default_factory=list)
    track: str = "semantic"
    readme_excerpt: str = ""
    root_entries: list[str] = field(default_factory=list)
    activity_score: float = 0.0
    semantic_score: float = 0.0
    exact_score: float = 0.0
    score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GitHubUserCandidate:
    login: str
    url: str
    name: str = ""
    bio: str = ""
    followers: int = 0
    public_repos: int = 0
    track: str = "semantic"
    score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepoInspection:
    full_name: str
    readme_excerpt: str = ""
    languages: dict[str, int] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    root_entries: list[str] = field(default_factory=list)
    selected_files: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProfileInspection:
    login: str
    url: str
    name: str = ""
    bio: str = ""
    followers: int = 0
    public_repos: int = 0
    readme_excerpt: str = ""
    repos: list[GitHubRepoCandidate] = field(default_factory=list)
    primary_languages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["repos"] = [r.to_dict() for r in self.repos]
        return data


@dataclass
class SearchPlan:
    input_query: str
    target: str = "mixed"
    exact_terms: list[str] = field(default_factory=list)
    semantic_terms: list[str] = field(default_factory=list)
    must_keep: list[str] = field(default_factory=list)
    github_queries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResult:
    input_query: str
    query_plan: SearchPlan
    repositories: list[GitHubRepoCandidate] = field(default_factory=list)
    users: list[GitHubUserCandidate] = field(default_factory=list)
    total_count: int = 0
    response_time_ms: int = 0
    retry_info: dict[str, Any] = field(default_factory=dict)
    rate_limit: dict[str, Any] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_query": self.input_query,
            "github_query": " ".join(self.query_plan.semantic_terms),
            "target": self.query_plan.target,
            "query_plan": self.query_plan.to_dict(),
            "repositories": [r.to_dict() for r in self.repositories],
            "users": [u.to_dict() for u in self.users],
            "candidates": [r.to_dict() for r in self.repositories] + [u.to_dict() for u in self.users],
            "total_count": self.total_count,
            "response_time_ms": self.response_time_ms,
            "retry_info": self.retry_info,
            "rate_limit": self.rate_limit,
            "stages": self.stages,
        }


@dataclass
class SkillBundle:
    name: str
    root: str
    files: dict[str, str]
    install_commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactWriteResult:
    path: str
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
