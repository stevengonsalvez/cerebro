from __future__ import annotations

import dataclasses
import pathlib
import sys
import types
from typing import Any

from fastapi.testclient import TestClient

from cerebro.ui.server import create_app


def test_index_serves_static_workbench() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Cerebro signal workbench" in response.text
    assert 'id="searchForm"' in response.text


def test_health_reports_backend_availability(monkeypatch: Any) -> None:
    install_fake_backends(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "cerebro-ui",
        "backends": {"git_search": True, "cracked_devs": True},
    }


def test_git_search_calls_backend_with_settings(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []
    settings = object()

    def search_github(
        query: str,
        settings: Any = None,
        target: str = "mixed",
        limit: int = 10,
        deep: bool = False,
    ) -> dict[str, Any]:
        calls.append(
            {
                "query": query,
                "settings": settings,
                "target": target,
                "limit": limit,
                "deep": deep,
            }
        )
        return {
            "input_query": query,
            "target": target,
            "total_count": 1,
            "candidates": [
                {
                    "full_name": "filiksyos/gittoskill",
                    "reason": "exact token match",
                }
            ],
        }

    install_fake_backends(monkeypatch, search_github=search_github)
    client = TestClient(create_app(settings=settings))

    response = client.post(
        "/api/git-search",
        json={
            "query": "  gittoskill  ",
            "target": "repositories",
            "limit": 5,
            "deep": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["candidates"][0]["full_name"] == "filiksyos/gittoskill"
    assert calls == [
        {
            "query": "gittoskill",
            "settings": settings,
            "target": "repositories",
            "limit": 5,
            "deep": True,
        }
    ]


def test_repo_skill_endpoint_serializes_dataclass_and_paths(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []
    settings = object()

    @dataclasses.dataclass
    class SkillResult:
        name: str
        path: pathlib.Path
        dry_run: bool

    def generate_repo_skill(
        full_name: str,
        settings: Any = None,
        write: bool = False,
        dry_run: bool = True,
    ) -> SkillResult:
        calls.append(
            {
                "full_name": full_name,
                "settings": settings,
                "write": write,
                "dry_run": dry_run,
            }
        )
        return SkillResult(
            name="filiksyos--gittoskill",
            path=pathlib.Path("vault/Skills/cracked-devs/repos/filiksyos--gittoskill"),
            dry_run=dry_run,
        )

    install_fake_backends(monkeypatch, generate_repo_skill=generate_repo_skill)
    client = TestClient(create_app(settings=settings))

    response = client.post(
        "/api/cracked-devs/repo",
        json={"full_name": " filiksyos/gittoskill ", "write": True, "dry_run": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "filiksyos--gittoskill",
        "path": "vault/Skills/cracked-devs/repos/filiksyos--gittoskill",
        "dry_run": True,
    }
    assert calls == [
        {
            "full_name": "filiksyos/gittoskill",
            "settings": settings,
            "write": True,
            "dry_run": True,
        }
    ]


def test_user_skill_endpoint_supports_async_backend(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []
    settings = object()

    async def generate_user_skill(
        login: str,
        settings: Any = None,
        write: bool = False,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        calls.append(
            {
                "login": login,
                "settings": settings,
                "write": write,
                "dry_run": dry_run,
            }
        )
        return {"login": login, "skill_path": "vault/Skills/cracked-devs/users/filiksyos"}

    install_fake_backends(monkeypatch, generate_user_skill=generate_user_skill)
    client = TestClient(create_app(settings=settings))

    response = client.post(
        "/api/cracked-devs/user",
        json={"login": "@filiksyos", "write": False, "dry_run": True},
    )

    assert response.status_code == 200
    assert response.json()["login"] == "filiksyos"
    assert calls == [
        {
            "login": "filiksyos",
            "settings": settings,
            "write": False,
            "dry_run": True,
        }
    ]


def test_missing_backend_returns_service_unavailable(monkeypatch: Any) -> None:
    def fail_import(module_name: str) -> None:
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr("cerebro.ui.server.importlib.import_module", fail_import)
    client = TestClient(create_app())

    response = client.post("/api/git-search", json={"query": "gittoskill"})

    assert response.status_code == 503
    assert response.json()["detail"] == "git-search backend is not available"


def install_fake_backends(
    monkeypatch: Any,
    search_github: Any | None = None,
    generate_repo_skill: Any | None = None,
    generate_user_skill: Any | None = None,
) -> None:
    gitintel = types.ModuleType("cerebro.gitintel")
    gitintel.__path__ = []

    repo_search = types.ModuleType("cerebro.gitintel.repo_search")
    repo_search.search_github = search_github or default_search_github

    skillgen = types.ModuleType("cerebro.gitintel.skillgen")
    skillgen.generate_repo_skill = generate_repo_skill or default_generate_repo_skill
    skillgen.generate_user_skill = generate_user_skill or default_generate_user_skill

    monkeypatch.setitem(sys.modules, "cerebro.gitintel", gitintel)
    monkeypatch.setitem(sys.modules, "cerebro.gitintel.repo_search", repo_search)
    monkeypatch.setitem(sys.modules, "cerebro.gitintel.skillgen", skillgen)


def default_search_github(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"input_query": args[0], "candidates": []}


def default_generate_repo_skill(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"full_name": args[0]}


def default_generate_user_skill(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"login": args[0]}
