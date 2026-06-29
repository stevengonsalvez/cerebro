from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any


_SAFE_SLUG = re.compile(r"[^a-z0-9]+")


def write_brief(brief: Any, settings_or_path: Any, *, dry_run: bool | None = None) -> dict:
    """Write a durable research/search brief under Briefs."""
    root = _vault_root(settings_or_path, dry_run)
    brief_date = _brief_date(brief)
    slug = _brief_slug(brief)
    path = root / "Briefs" / f"{brief_date}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(brief_markdown(brief, brief_date=brief_date, slug=slug), encoding="utf-8")
    return {"kind": "brief", "slug": slug, "date": brief_date, "path": str(path)}


def write_search_brief(query: str, result: Mapping[str, Any], settings_or_path: Any, *, dry_run: bool | None = None) -> dict:
    candidates = result.get("candidates") or []
    repos = result.get("repositories") or []
    users = result.get("users") or []
    entities = []
    entities.extend(f"repo/{repo.get('full_name')}" for repo in repos[:5] if repo.get("full_name"))
    entities.extend(f"developer/{user.get('login')}" for user in users[:5] if user.get("login"))
    brief = {
        "title": f"Git search: {query}",
        "slug": _brief_slug({"title": query}),
        "summary": f"GitHub search results for `{query}` with exact and semantic tracks.",
        "why_it_matters": [
            "This search was promoted from transient results into a durable Cerebro brief.",
            "Use linked entity notes and candidate reasons to decide whether to inspect or watch these repos/users.",
        ],
        "entities": entities,
        "topic_tags": ["git-search"],
        "source_tags": ["github/search"],
        "github_evidence": candidates[:10],
        "source_artifacts": result.get("written_artifacts", []),
        "next_actions": ["inspect top repo", "generate cracked-devs skill", "add watchlist query if useful"],
    }
    return write_brief(brief, settings_or_path, dry_run=dry_run)


def brief_markdown(brief: Any, *, brief_date: str | None = None, slug: str | None = None) -> str:
    title = _text(_first(brief, "title", "question", default="Cerebro Brief"))
    brief_date = brief_date or _brief_date(brief)
    slug = slug or _brief_slug(brief)
    generated_at = _text(_get(brief, "generated_at"), default=brief_date)
    typed_tags = _typed_tags(brief)
    entities = _text_list(_get(brief, "entities"))
    frontmatter = _frontmatter(
        [
            ("type", "cerebro-brief"),
            ("title", title),
            ("date", brief_date),
            ("slug", slug),
            ("score", _get(brief, "score")),
            ("confidence", _get(brief, "confidence")),
            ("entities", entities),
            ("tags", typed_tags["tags"]),
            ("topic_tags", typed_tags["topic_tags"]),
            ("source_tags", typed_tags["source_tags"]),
            ("entity_tags", typed_tags["entity_tags"]),
            ("artifact_tags", typed_tags["artifact_tags"]),
            ("workflow_tags", typed_tags["workflow_tags"]),
            ("generated_at", generated_at),
            ("rating", None),
        ]
    )
    answer = _first(brief, "answer", "summary", "body", default="No answer supplied.")
    body = [
        f"# {title}",
        _section("Answer", _paragraphs(answer)),
        _section("Why It Matters", _paragraphs(_first(brief, "why_it_matters", "why_matched", "reasons", default=[]))),
        _section("Entities", _bullets(entities, "No entities supplied.")),
        _section("Evidence", _evidence_table(_first(brief, "evidence", "citations", default=[]))),
        _section("Source Artifacts", _links(_first(brief, "source_artifacts", "artifacts", default=[]))),
        _section("GitHub Evidence", _evidence_table(_first(brief, "github_evidence", "github", default=[]))),
        _section("Next Actions", _bullets(_first(brief, "next_actions", "followups", default=[]), "No next actions supplied.")),
    ]
    return frontmatter + "\n\n" + "\n\n".join(body).rstrip() + "\n"


def _vault_root(settings_or_path: Any, dry_run: bool | None) -> Path:
    if hasattr(settings_or_path, "vault_path"):
        base = Path(settings_or_path.vault_path)
        use_scratch = bool(getattr(settings_or_path, "dry_run", False)) if dry_run is None else dry_run
    else:
        base = Path(settings_or_path)
        use_scratch = bool(dry_run)
    return base / "_scratch" if use_scratch else base


def _brief_date(brief: Any) -> str:
    value = _first(brief, "date", "brief_date")
    if value:
        return _text(value)[:10]
    generated_at = _get(brief, "generated_at")
    if generated_at:
        return _text(generated_at)[:10]
    return date.today().isoformat()


def _brief_slug(brief: Any) -> str:
    value = _first(brief, "slug", "id", "title", "question", default="brief")
    slug = _SAFE_SLUG.sub("-", _text(value).lower()).strip("-")
    return slug[:80].strip("-") or "brief"


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _first(item: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = _get(item, key)
        if value is not None and value != "":
            return value
    return default


def _frontmatter(items: list[tuple[str, Any]]) -> str:
    lines = ["---"]
    for key, value in items:
        if value is None:
            lines.append(f"{key}:")
        elif isinstance(value, list):
            lines.append(f"{key}: {_yaml_list(value)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(_text(value), ensure_ascii=False)


def _yaml_list(values: Iterable[Any]) -> str:
    return "[" + ", ".join(json.dumps(_text(value), ensure_ascii=False) for value in values) + "]"


def _typed_tags(item: Any) -> dict[str, list[str]]:
    topic_tags = _text_list(_first(item, "topic_tags", "topics", default=[]))
    source_tags = _text_list(_get(item, "source_tags"))
    entity_tags = sorted(set(_text_list(_get(item, "entity_tags")) + _text_list(_get(item, "entities"))))
    artifact_tags = sorted(set(_text_list(_get(item, "artifact_tags")) + ["cerebro/brief"]))
    workflow_tags = sorted(set(_text_list(_get(item, "workflow_tags")) + ["workflow/brief"]))
    tags = sorted(
        set(_text_list(_get(item, "tags")) + topic_tags + source_tags + entity_tags + artifact_tags + workflow_tags)
    )
    return {
        "tags": tags,
        "topic_tags": topic_tags,
        "source_tags": source_tags,
        "entity_tags": entity_tags,
        "artifact_tags": artifact_tags,
        "workflow_tags": workflow_tags,
    }


def _text_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [_text(value)]
    if isinstance(value, Mapping):
        return [_text(key) for key in sorted(value)]
    try:
        return [_text(item) for item in value if item is not None and _text(item) != ""]
    except TypeError:
        return [_text(value)]


def _rows(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, Mapping) or isinstance(value, str):
        return [value]
    return list(value)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return " ".join(str(value).replace("|", "\\|").split())


def _section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.rstrip()}"


def _paragraphs(value: Any) -> str:
    rows = _rows(value)
    if not rows:
        return "No evidence supplied."
    if len(rows) == 1 and isinstance(rows[0], str):
        return _text(rows[0])
    return "\n".join(f"- {_item_summary(row)}" for row in rows)


def _bullets(value: Any, empty: str) -> str:
    rows = _rows(value)
    if not rows:
        return empty
    return "\n".join(f"- {_link(row)}" for row in rows)


def _links(value: Any) -> str:
    return _bullets(value, "No source artifacts supplied.")


def _link(row: Any) -> str:
    if isinstance(row, str):
        return _text(row)
    label = _first(row, "title", "name", "full_name", "login", "path", "url", default="artifact")
    url = _first(row, "url", "html_url", "path", default="")
    detail = _first(row, "reason", "summary", "description", default="")
    link = f"[{_text(label)}]({_text(url)})" if url else _text(label)
    return f"{link} - {_text(detail)}" if detail else link


def _evidence_table(value: Any) -> str:
    rows = _rows(value)
    if not rows:
        return "No evidence supplied."
    table = ["| source | item | reason | score |", "|---|---|---|---:|"]
    for row in rows:
        if isinstance(row, str):
            table.append(f"|  | {_text(row)} |  |  |")
            continue
        source = _first(row, "source", "kind", "type", default="")
        title = _first(row, "title", "name", "query", "path", "url", default="evidence")
        url = _first(row, "url", "html_url", "path", default="")
        item = f"[{_text(title)}]({_text(url)})" if url else _text(title)
        reason = _first(row, "reason", "match", "summary", "description", default="")
        table.append(f"| {_text(source)} | {item} | {_text(reason)} | {_score(_get(row, 'score'))} |")
    return "\n".join(table)


def _item_summary(row: Any) -> str:
    if isinstance(row, str):
        return _text(row)
    if isinstance(row, Mapping):
        preferred = _first(row, "summary", "reason", "title", "name", "url", default="")
        if preferred:
            return _text(preferred)
        return ", ".join(f"{_text(k)}={_text(v)}" for k, v in sorted(row.items()))
    return _text(row)


def _score(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _text(value)
