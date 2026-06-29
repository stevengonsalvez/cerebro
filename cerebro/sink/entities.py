from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


def write_repo(repo: Any, settings_or_path: Any, *, dry_run: bool | None = None) -> dict:
    """Write a repo entity note under Entities/repos."""
    root = _vault_root(settings_or_path, dry_run)
    owner, name, full_name = _repo_identity(repo)
    path = root / "Entities" / "repos" / f"{_safe_segment(owner)}--{_safe_segment(name)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(repo_markdown(repo), encoding="utf-8")
    return {"kind": "repo", "full_name": full_name, "path": str(path)}


def write_developer(developer: Any, settings_or_path: Any, *, dry_run: bool | None = None) -> dict:
    """Write a developer entity note under Entities/developers."""
    root = _vault_root(settings_or_path, dry_run)
    login = _required_text(developer, "login").removeprefix("@")
    path = root / "Entities" / "developers" / f"{_safe_segment(login)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(developer_markdown(developer), encoding="utf-8")
    return {"kind": "developer", "login": login, "path": str(path)}


write_repo_entity = write_repo
write_developer_entity = write_developer


def repo_markdown(repo: Any) -> str:
    owner, name, full_name = _repo_identity(repo)
    generated_at = _text(_get(repo, "generated_at"), default=date.today().isoformat())
    tags = _typed_tags(repo, "repo", [f"github/{owner}", f"repo/{name}"])
    frontmatter = _frontmatter(
        [
            ("type", "cerebro-entity"),
            ("entity_type", "repo"),
            ("owner", owner),
            ("repo", name),
            ("full_name", full_name),
            ("url", _first(repo, "url", "html_url", "homepage", default=f"https://github.com/{full_name}")),
            ("score", _get(repo, "score")),
            ("tags", tags["tags"]),
            ("topic_tags", tags["topic_tags"]),
            ("source_tags", tags["source_tags"]),
            ("entity_tags", tags["entity_tags"]),
            ("artifact_tags", tags["artifact_tags"]),
            ("workflow_tags", tags["workflow_tags"]),
            ("generated_at", generated_at),
            ("rating", None),
        ]
    )
    body = [
        f"# {full_name}",
        _section("What It Is", _text(_first(repo, "summary", "description"), "No summary supplied.")),
        _section("Why It Matched", _paragraphs(_first(repo, "why_matched", "reasons", "ranking_reasons"))),
        _section("Activity Snapshot", _repo_activity(repo)),
        _section("Stack Signals", _stack_signals(repo)),
        _section("Search Evidence", _evidence_table(_first(repo, "search_evidence", "evidence", default=[]))),
        _section("Related Signals", _links(_first(repo, "related_signals", "signals", default=[]))),
        _section("Generated Skills", _links(_first(repo, "generated_skills", "skills", default=[]))),
    ]
    return frontmatter + "\n\n" + "\n\n".join(body).rstrip() + "\n"


def developer_markdown(developer: Any) -> str:
    login = _required_text(developer, "login").removeprefix("@")
    display_name = _first(developer, "display_name", "name", default="")
    generated_at = _text(_get(developer, "generated_at"), default=date.today().isoformat())
    tags = _typed_tags(developer, "developer", [f"github/{login}", f"developer/{login}"])
    top_repos = _first(developer, "top_repos", "notable_repos", "repos", default=[])
    frontmatter = _frontmatter(
        [
            ("type", "cerebro-entity"),
            ("entity_type", "developer"),
            ("login", login),
            ("display_name", display_name),
            ("profile_url", _first(developer, "profile_url", "html_url", "url", default=f"https://github.com/{login}")),
            ("followers", _get(developer, "followers")),
            ("tags", tags["tags"]),
            ("topic_tags", tags["topic_tags"]),
            ("source_tags", tags["source_tags"]),
            ("entity_tags", tags["entity_tags"]),
            ("artifact_tags", tags["artifact_tags"]),
            ("workflow_tags", tags["workflow_tags"]),
            ("primary_languages", _text_list(_get(developer, "primary_languages"))),
            ("top_repos", _repo_names(top_repos)),
            ("generated_at", generated_at),
            ("rating", None),
        ]
    )
    heading = f"@{login}" if not display_name else f"{display_name} (@{login})"
    body = [
        f"# {heading}",
        _section("What They Build", _paragraphs(_first(developer, "what_they_build", "summary", "bio"))),
        _section("Style Signals", _paragraphs(_first(developer, "style_signals", "style", default=[]))),
        _section("Stack Clues", _stack_clues(developer)),
        _section("Notable Repos", _links(top_repos)),
        _section("Identity Links", _links(_first(developer, "identity_links", "links", default=[]))),
        _section("Evidence", _evidence_table(_first(developer, "evidence", "source_evidence", default=[]))),
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


def _repo_identity(repo: Any) -> tuple[str, str, str]:
    full_name = _first(repo, "full_name", "name_with_owner", default="")
    owner = _get(repo, "owner")
    if isinstance(owner, Mapping) or hasattr(owner, "login"):
        owner = _first(owner, "login", "name", default="")
    name = _first(repo, "repo", "name", default="")
    if full_name and "/" in str(full_name):
        owner_from_full, name_from_full = str(full_name).split("/", 1)
        owner = owner or owner_from_full
        name = name or name_from_full
    if not owner or not name:
        raise ValueError("repo entity requires owner/repo, full_name, or name_with_owner")
    owner_text = _safe_segment(str(owner))
    name_text = _safe_segment(str(name))
    return owner_text, name_text, f"{owner_text}/{name_text}"


def _required_text(item: Any, key: str) -> str:
    value = _get(item, key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"developer entity requires {key}")
    return _text(value)


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


def _safe_segment(value: str) -> str:
    segment = _SAFE_SEGMENT.sub("-", value.strip().strip("/@")).strip("-.")
    if not segment:
        raise ValueError("path segment cannot be empty")
    return segment


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


def _typed_tags(item: Any, entity_type: str, defaults: list[str]) -> dict[str, list[str]]:
    topic_tags = _text_list(_first(item, "topic_tags", "topics", default=[]))
    source_tags = _text_list(_get(item, "source_tags"))
    entity_tags = sorted(set(_text_list(_get(item, "entity_tags")) + [f"entity/{entity_type}", *defaults]))
    artifact_tags = sorted(set(_text_list(_get(item, "artifact_tags")) + ["cerebro/entity"]))
    workflow_tags = _text_list(_get(item, "workflow_tags"))
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


def _repo_activity(repo: Any) -> str:
    fields = [
        ("Stars", _first(repo, "stars", "stargazers_count")),
        ("Forks", _get(repo, "forks")),
        ("Open issues", _first(repo, "open_issues", "open_issues_count")),
        ("Primary language", _first(repo, "language", "primary_language")),
        ("Updated", _first(repo, "updated_at", "pushed_at")),
        ("License", _first(repo, "license", "license_name")),
    ]
    return "\n".join(f"- **{label}:** {_text(value)}" for label, value in fields if value not in (None, "", [])) or "No activity snapshot supplied."


def _stack_signals(repo: Any) -> str:
    languages = _text_list(_first(repo, "languages", "primary_languages", default=[]))
    topics = _text_list(_first(repo, "topics", "topic_tags", default=[]))
    rows = []
    if languages:
        rows.append(f"- **Languages:** {', '.join(languages)}")
    if topics:
        rows.append(f"- **Topics:** {', '.join(topics)}")
    stack = _paragraphs(_get(repo, "stack_signals")) if _get(repo, "stack_signals") else ""
    if stack:
        rows.append(stack)
    return "\n".join(rows) or "No stack signals supplied."


def _stack_clues(developer: Any) -> str:
    languages = _text_list(_get(developer, "primary_languages"))
    topics = _text_list(_first(developer, "topics", "topic_tags", default=[]))
    rows = []
    if languages:
        rows.append(f"- **Languages:** {', '.join(languages)}")
    if topics:
        rows.append(f"- **Topics:** {', '.join(topics)}")
    clues = _paragraphs(_get(developer, "stack_clues")) if _get(developer, "stack_clues") else ""
    if clues:
        rows.append(clues)
    return "\n".join(rows) or "No stack clues supplied."


def _links(value: Any) -> str:
    rows = _rows(value)
    if not rows:
        return "No links supplied."
    return "\n".join(f"- {_link(row)}" for row in rows)


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
        score = _score(_get(row, "score"))
        table.append(f"| {_text(source)} | {item} | {_text(reason)} | {score} |")
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


def _repo_names(repos: Any) -> list[str]:
    names = []
    for repo in _rows(repos):
        if isinstance(repo, str):
            names.append(_text(repo))
        else:
            names.append(_text(_first(repo, "full_name", "name_with_owner", "name", default="")))
    return [name for name in names if name]


def _score(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _text(value)
