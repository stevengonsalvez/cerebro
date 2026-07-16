from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .repo_search import search_github


def deep_search(query: str, settings=None, target: str = "mixed", limit: int = 10) -> Iterator[dict[str, Any]]:
    yield {"stage": "query_plan", "status": "started", "query": query}
    result = search_github(query, settings=settings, target=target, limit=limit, deep=True)
    for stage in result.get("stages", []):
        name = stage.get("stage", "stage")
        if name != "query_plan":
            yield {"stage": name, "status": "completed", **stage}
    yield {"stage": "result", "status": "completed", "result": result}
