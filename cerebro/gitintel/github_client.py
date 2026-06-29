from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

import requests

from .cache import GitIntelCache

API = "https://api.github.com"


class GitHubClientError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, settings=None, token: str | None = None, cache: GitIntelCache | None = None):
        cfg = getattr(settings, "github", {}) or {}
        token_env = cfg.get("token_env", "GITHUB_TOKEN")
        self.token = token if token is not None else os.environ.get(token_env, "")
        self.timeout = int(cfg.get("request_timeout_seconds", 20))
        self.cache = cache or GitIntelCache(cfg.get("cache_path"), int(cfg.get("cache_ttl_hours", 24)))
        self.rate_limit: dict[str, Any] = {}

    def _cache_key(self, method: str, path: str, params: dict | None) -> str:
        payload = json.dumps({
            "v": 1,
            "method": method,
            "path": path,
            "params": params or {},
            "auth": bool(self.token),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def request(self, path: str, params: dict | None = None) -> Any:
        key = self._cache_key("GET", path, params)
        cached = self.cache.get_response(key)
        if cached:
            status, data = cached
            if 200 <= status < 300:
                return data
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = path if path.startswith("http") else f"{API}{path}"
        try:
            resp = requests.get(url, params=params or {}, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise GitHubClientError(f"GitHub request failed for {path}: {exc}") from exc
        self.rate_limit = {
            "limit": resp.headers.get("X-RateLimit-Limit", ""),
            "remaining": resp.headers.get("X-RateLimit-Remaining", ""),
            "reset": resp.headers.get("X-RateLimit-Reset", ""),
            "authenticated": bool(self.token),
        }
        try:
            data = resp.json()
        except ValueError:
            data = {"text": resp.text}
        self.cache.set_response(key, resp.status_code, data)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            msg = data.get("message") if isinstance(data, dict) else str(data)
            raise GitHubClientError(f"GitHub {resp.status_code} for {path}: {msg}")
        return data

    def search_repositories(self, query: str, limit: int = 10) -> dict:
        return self.request("/search/repositories", {"q": query, "per_page": min(limit, 100)}) or {}

    def search_users(self, query: str, limit: int = 10) -> dict:
        return self.request("/search/users", {"q": query, "per_page": min(limit, 100)}) or {}

    def get_repo(self, owner: str, repo: str) -> dict | None:
        return self.request(f"/repos/{owner}/{repo}")

    def get_readme(self, owner: str, repo: str) -> str:
        data = self.request(f"/repos/{owner}/{repo}/readme")
        if not data:
            return ""
        content = data.get("content", "")
        if data.get("encoding") == "base64" and content:
            try:
                return base64.b64decode(content).decode("utf-8", errors="replace")
            except ValueError:
                return ""
        return str(content)

    def get_languages(self, owner: str, repo: str) -> dict:
        return self.request(f"/repos/{owner}/{repo}/languages") or {}

    def get_topics(self, owner: str, repo: str) -> list[str]:
        data = self.request(f"/repos/{owner}/{repo}/topics") or {}
        return data.get("names", []) if isinstance(data, dict) else []

    def get_repo_contents(self, owner: str, repo: str, path: str = "") -> list[dict]:
        data = self.request(f"/repos/{owner}/{repo}/contents/{path}".rstrip("/"))
        return data if isinstance(data, list) else []

    def get_user(self, login: str) -> dict | None:
        return self.request(f"/users/{login}")

    def get_user_repos(self, login: str, limit: int = 20) -> list[dict]:
        data = self.request(f"/users/{login}/repos", {
            "per_page": min(limit, 100),
            "sort": "updated",
            "direction": "desc",
        })
        return data if isinstance(data, list) else []
