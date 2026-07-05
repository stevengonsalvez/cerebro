from __future__ import annotations

import dataclasses
import inspect
import importlib
import pathlib
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"


class GitSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    target: Literal["repositories", "users", "mixed"] = "mixed"
    limit: int = Field(default=10, ge=1, le=50)
    deep: bool = False


class RepoSkillRequest(BaseModel):
    full_name: str = Field(min_length=1)
    write: bool = False
    dry_run: bool = True


class UserSkillRequest(BaseModel):
    login: str = Field(min_length=1)
    write: bool = False
    dry_run: bool = True


class ArtifactRequest(BaseModel):
    payload: dict[str, Any]
    dry_run: bool = True


def create_app(settings: Any | None = None) -> FastAPI:
    app = FastAPI(title="Cerebro UI", version="0.1.0")
    app.state.cerebro_settings = settings

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "cerebro-ui",
            "backends": {
                "git_search": _backend_available(
                    "cerebro.gitintel.repo_search", "search_github"
                ),
                "cracked_devs": _backend_available(
                    "cerebro.gitintel.skillgen",
                    "generate_repo_skill",
                    "generate_user_skill",
                ),
            },
        }

    @app.post("/api/git-search")
    async def git_search(payload: GitSearchRequest) -> Any:
        search_github = _load_backend(
            "cerebro.gitintel.repo_search", "search_github", "git-search"
        )
        result = await _maybe_await(
            search_github(
                payload.query.strip(),
                settings=app.state.cerebro_settings,
                target=payload.target,
                limit=payload.limit,
                deep=payload.deep,
            )
        )
        return _to_response(result)

    @app.post("/api/cracked-devs/repo")
    async def cracked_devs_repo(payload: RepoSkillRequest) -> Any:
        generate_repo_skill = _load_backend(
            "cerebro.gitintel.skillgen", "generate_repo_skill", "repo skill generation"
        )
        result = await _maybe_await(
            generate_repo_skill(
                payload.full_name.strip(),
                settings=app.state.cerebro_settings,
                write=payload.write,
                dry_run=payload.dry_run,
            )
        )
        return _to_response(result)

    @app.post("/api/cracked-devs/user")
    async def cracked_devs_user(payload: UserSkillRequest) -> Any:
        generate_user_skill = _load_backend(
            "cerebro.gitintel.skillgen", "generate_user_skill", "user skill generation"
        )
        result = await _maybe_await(
            generate_user_skill(
                payload.login.strip().removeprefix("@"),
                settings=app.state.cerebro_settings,
                write=payload.write,
                dry_run=payload.dry_run,
            )
        )
        return _to_response(result)

    @app.post("/api/artifacts/entity")
    async def write_entity(payload: ArtifactRequest) -> Any:
        data = dict(payload.payload)
        kind = data.get("entity_type") or data.get("kind")
        if kind in {"developer", "user"} or data.get("login"):
            writer = _load_backend("cerebro.sink.entities", "write_developer", "developer entity writer")
        else:
            writer = _load_backend("cerebro.sink.entities", "write_repo", "repo entity writer")
        result = await _maybe_await(writer(data, app.state.cerebro_settings or "vault", dry_run=payload.dry_run))
        return _to_response(result)

    @app.post("/api/artifacts/brief")
    async def write_brief(payload: ArtifactRequest) -> Any:
        writer = _load_backend("cerebro.sink.briefs", "write_brief", "brief writer")
        result = await _maybe_await(writer(payload.payload, app.state.cerebro_settings or "vault", dry_run=payload.dry_run))
        return _to_response(result)

    @app.get("/api/artifacts/recent")
    async def recent_artifacts() -> dict[str, Any]:
        settings_obj = app.state.cerebro_settings
        root = pathlib.Path(getattr(settings_obj, "vault_path", "vault"))
        if getattr(settings_obj, "dry_run", False):
            root = root / "_scratch"
        paths = []
        for folder in ("Entities", "Briefs", "Skills"):
            base = root / folder
            if base.exists():
                paths.extend(str(path) for path in sorted(base.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:25])
        return {"root": str(root), "artifacts": paths[:50]}

    return app


def _load_backend(module_name: str, attr_name: str, label: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{label} backend is not available",
        ) from exc

    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{label} backend is missing {attr_name}",
        ) from exc


def _backend_available(module_name: str, *attrs: str) -> bool:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return False
    return all(hasattr(module, attr) for attr in attrs)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _to_response(value: Any) -> Any:
    return jsonable_encoder(_to_jsonable(value))


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, pathlib.Path | datetime | date | Enum):
        return str(value)
    if dataclasses.is_dataclass(value):
        return _to_jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if hasattr(value, "dict") and callable(value.dict):
        return _to_jsonable(value.dict())
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _to_jsonable(value.to_dict())
    if hasattr(value, "__dict__"):
        return {
            key: _to_jsonable(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value
