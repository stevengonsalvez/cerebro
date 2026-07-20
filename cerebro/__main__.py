from __future__ import annotations

import argparse
import json
from typing import Any

from . import __version__


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="cerebro", description="Daily tech-signal pipeline → Obsidian"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="write to _scratch/, mute ntfy")
    ap.add_argument("--health", action="store_true",
                    help="print per-source yield/failure history and exit")
    ap.add_argument("--beast", action="store_true",
                    help="X firehose: pull every tweet in window, analyse all, walk threads (heavy tokens)")
    ap.add_argument("--version", action="version", version=f"cerebro {__version__}")
    sub = ap.add_subparsers(dest="command")

    run_ap = sub.add_parser("run", help="run daily pipeline")
    run_ap.add_argument("--dry-run", action="store_true", help="write to _scratch/, mute ntfy")

    sub.add_parser("health", help="print source health")

    gs = sub.add_parser("git-search", help="natural-language GitHub repo/person search")
    gs.add_argument("query")
    gs.add_argument("--target", choices=["mixed", "repositories", "users"], default="mixed")
    gs.add_argument("--limit", type=int, default=10)
    gs.add_argument("--deep", action="store_true")
    gs.add_argument("--write", action="store_true", help="write entity/brief artifacts for top results")

    cd = sub.add_parser("cracked-devs", help="generate repo/user intelligence and skill bundles")
    cd_sub = cd.add_subparsers(dest="cracked_kind", required=True)
    cd_repo = cd_sub.add_parser("repo", help="generate repo skill")
    cd_repo.add_argument("full_name")
    cd_repo.add_argument("--write-skill", action="store_true")
    cd_repo.add_argument("--write-entity", action="store_true")
    cd_repo.add_argument("--write-brief", action="store_true")
    cd_repo.add_argument("--install", choices=["repo", "global"])
    cd_repo.add_argument("--dry-run", action="store_true")
    cd_user = cd_sub.add_parser("user", help="generate user skill")
    cd_user.add_argument("login")
    cd_user.add_argument("--write-skill", action="store_true")
    cd_user.add_argument("--write-entity", action="store_true")
    cd_user.add_argument("--write-brief", action="store_true")
    cd_user.add_argument("--install", choices=["repo", "global"])
    cd_user.add_argument("--dry-run", action="store_true")
    cd_roster = cd_sub.add_parser("roster", help="inspect and enrich the cracked-dev roster")
    cd_roster.add_argument("action", choices=["list", "enrich", "suggest"])
    cd_roster.add_argument("--tier", type=int, default=None, help="filter to tier <= N")
    cd_roster.add_argument("--write", action="store_true",
                           help="write enrichment back to config/cracked_devs.yaml")
    cd_roster.add_argument("--overwrite", action="store_true",
                           help="let resolution replace curated values (default: fill blanks only)")
    cd_roster.add_argument("--limit", type=int, default=20, help="suggest: max candidates")

    serve = sub.add_parser("serve", help="serve local Cerebro UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=4317)
    args = ap.parse_args()

    if args.command == "health" or args.health:
        from .state import State
        s = State()
        print(f"{'source':16}{'runs':>6}{'avg':>8}{'zero/fail':>11}   last_seen")
        for src, runs, avg, zf, last in s.source_summary():
            print(f"{src:16}{runs:>6}{avg:>8}{zf:>11}   {last}")
        s.close()
        return

    from .config import load

    if args.command == "git-search":
        from .gitintel.repo_search import search_github
        settings = load(allow_example=True)
        result = search_github(args.query, settings=settings, target=args.target, limit=args.limit, deep=args.deep)
        if args.write:
            try:
                from .sink import briefs, entities
                written = []
                for repo in result.get("repositories", [])[:3]:
                    written.append(entities.write_repo(repo, settings))
                for user in result.get("users", [])[:3]:
                    written.append(entities.write_developer(user, settings))
                if result.get("repositories") or result.get("users"):
                    written.append(briefs.write_search_brief(args.query, result, settings))
                result["written_artifacts"] = written
            except Exception as exc:  # noqa: BLE001 - artifact write must not hide search result
                result["artifact_error"] = str(exc)
        print(json.dumps(result, indent=2))
        return

    if args.command == "cracked-devs":
        from .gitintel import skillgen
        settings = load(
            dry_run_override=True if getattr(args, "dry_run", False) else None,
            allow_example=True,
        )
        if args.cracked_kind == "roster":
            print(json.dumps(_run_roster(args, settings), indent=2))
            return
        if args.install:
            raise SystemExit("--install is intentionally explicit but not automated yet; generated bundle includes commands")
        if args.cracked_kind == "repo":
            result = skillgen.generate_repo_skill(
                args.full_name, settings=settings, write=args.write_skill, dry_run=settings.dry_run
            )
            written = _write_cracked_repo_artifacts(result, settings, write_entity=args.write_entity, write_brief=args.write_brief)
        else:
            result = skillgen.generate_user_skill(
                args.login, settings=settings, write=args.write_skill, dry_run=settings.dry_run
            )
            written = _write_cracked_user_artifacts(result, settings, write_entity=args.write_entity, write_brief=args.write_brief)
        if written:
            result["written_artifacts"] = written
        print(json.dumps(result, indent=2))
        return

    if args.command == "serve":
        settings = load(allow_example=True)
        from .ui.server import create_app
        import uvicorn
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return

    from .orchestrator import run

    dry_run_requested = bool(args.dry_run or getattr(args, "dry_run", False))
    settings = load(
        dry_run_override=True if dry_run_requested else None,
        allow_example=dry_run_requested,
    )
    if args.beast:
        settings.sources.setdefault("x", {})["beast"] = True
    st, paths = run(settings)
    total = st.input_tokens + st.output_tokens + st.cache_read + st.cache_creation
    print(
        f"\n✓ {st.raw} raw → {st.after_dedup} deduped → {st.after_triage} triaged → "
        f"{st.digested} in briefing  (dry_run={settings.dry_run}, x_ok={st.x_ok})"
    )
    print(
        f"  tokens: {total:,} total (in {st.input_tokens:,} · out {st.output_tokens:,} · "
        f"cache-read {st.cache_read:,} · cache-create {st.cache_creation:,}) · "
        f"{st.llm_calls} claude calls · ~${st.cost_usd:.2f} API-equiv"
    )
    print(f"  daily note: {paths['daily']}")


def _write_cracked_repo_artifacts(
    result: dict[str, Any],
    settings: Any,
    *,
    write_entity: bool,
    write_brief: bool,
) -> list[dict[str, Any]]:
    if not (write_entity or write_brief):
        return []
    from .sink import briefs, entities

    repo = result.get("repo") or {}
    written: list[dict[str, Any]] = []
    if write_entity:
        written.append(entities.write_repo(repo, settings))
    if write_brief:
        written.append(briefs.write_brief(_repo_intelligence_brief(repo, result), settings))
    return written


def _write_cracked_user_artifacts(
    result: dict[str, Any],
    settings: Any,
    *,
    write_entity: bool,
    write_brief: bool,
) -> list[dict[str, Any]]:
    if not (write_entity or write_brief):
        return []
    from .sink import briefs, cracked_devs as cracked_devs_sink, entities

    profile = result.get("profile") or {}
    written: list[dict[str, Any]] = []
    if write_entity:
        # Roster devs get their curated cross-platform links stamped onto the note.
        profile = cracked_devs_sink.attach_roster_identity(profile, getattr(settings, "cracked_devs", []))
        written.append(entities.write_developer(profile, settings))
    if write_brief:
        written.append(briefs.write_brief(_developer_intelligence_brief(profile, result), settings))
    return written


def _repo_intelligence_brief(repo: dict[str, Any], skill_result: dict[str, Any]) -> dict[str, Any]:
    full_name = _first_text(repo, "full_name", "name_with_owner", default=skill_result.get("target", "repo"))
    return {
        "title": f"Repo intelligence: {full_name}",
        "summary": _first_text(repo, "summary", "description", default=f"Generated cracked-devs repo intelligence for `{full_name}`."),
        "why_it_matters": _first_list(repo, "why_matched", "reasons", "ranking_reasons")
        or ["Repo evidence was promoted into Cerebro cracked-devs artifacts."],
        "entities": [f"repo/{full_name}"],
        "topic_tags": _first_list(repo, "topic_tags", "topics") or ["cracked-devs"],
        "source_tags": ["github/repo", "cracked-devs"],
        "artifact_tags": ["cracked-devs/repo"],
        "github_evidence": _first_list(repo, "search_evidence", "evidence"),
        "source_artifacts": _skill_artifacts(skill_result),
        "next_actions": ["review generated skill", "refresh before installation", "add repo to watchlist if useful"],
    }


def _developer_intelligence_brief(profile: dict[str, Any], skill_result: dict[str, Any]) -> dict[str, Any]:
    login = _first_text(profile, "login", default=skill_result.get("target", "developer")).removeprefix("@")
    repos = _first_list(profile, "top_repos", "notable_repos", "repos")
    repo_entities = [
        f"repo/{repo.get('full_name')}"
        for repo in repos
        if isinstance(repo, dict) and repo.get("full_name")
    ][:5]
    return {
        "title": f"Developer intelligence: @{login}",
        "summary": _first_text(profile, "summary", "bio", default=f"Generated cracked-devs developer intelligence for `@{login}`."),
        "why_it_matters": _first_list(profile, "style_signals", "reasons")
        or ["Developer evidence was promoted into Cerebro cracked-devs artifacts."],
        "entities": [f"developer/{login}", *repo_entities],
        "topic_tags": _first_list(profile, "topic_tags", "topics", "primary_languages") or ["cracked-devs"],
        "source_tags": ["github/profile", "cracked-devs"],
        "artifact_tags": ["cracked-devs/user"],
        "github_evidence": _first_list(profile, "evidence", "source_evidence"),
        "source_artifacts": _skill_artifacts(skill_result),
        "next_actions": ["review generated developer skill", "inspect notable repos", "refresh before installation"],
    }


def _skill_artifacts(skill_result: dict[str, Any]) -> list[dict[str, str]]:
    artifacts = []
    for title, key in (("Skill file", "skill"), ("Skill bundle", "bundle"), ("Manifest", "manifest")):
        value = skill_result.get(key)
        if value:
            artifacts.append({"title": title, "path": str(value)})
    return artifacts


def _first_text(data: dict[str, Any], *keys: str, default: Any = "") -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return " ".join(str(value).split())
    return " ".join(str(default).split())


def _first_list(data: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = data.get(key)
        if value:
            if isinstance(value, list):
                return value
            if isinstance(value, tuple):
                return list(value)
            return [value]
    return []


def _run_roster(args, settings) -> dict[str, Any]:
    """Dispatch `cracked-devs roster list|enrich|suggest` to a JSON-serialisable dict."""
    from .gitintel import roster as roster_mod

    devs, wiring = roster_mod.load_roster()
    if args.action == "list":
        shown = devs if args.tier is None else [d for d in devs if d.tier <= args.tier]
        wired = roster_mod.apply_to_sources({}, devs, wiring)
        return {
            "action": "list",
            "count": len(shown),
            "devs": [d.to_dict() for d in shown],
            "wiring": wiring,
            "wired": wired,
        }
    if args.action == "enrich":
        return _roster_enrich(args, settings, devs, roster_mod)
    return _roster_suggest(args, settings, devs, roster_mod)


def _roster_enrich(args, settings, devs, roster_mod) -> dict[str, Any]:
    from .gitintel import identity
    from .gitintel.github_client import GitHubClient

    client = GitHubClient(settings)
    changes: list[tuple[str, str, str]] = []
    diffs: list[dict[str, Any]] = []
    for dev in devs:
        if dev.github:
            ident = identity.resolve_from_github(dev.github, client)
        elif dev.blog:
            ident = identity.resolve_from_blog(dev.blog, client, fetch_page=_fetch_page)
        else:
            continue
        _, changed = identity.merge_into(dev, ident, overwrite=args.overwrite)
        for field_name in changed:
            value = getattr(dev, field_name)
            changes.append((dev.name, field_name, value))
            diffs.append({
                "dev": dev.name, "field": field_name, "value": value,
                "confidence": ident.confidence, "evidence": ident.evidence,
            })
    wrote = False
    if args.write and changes:
        _patch_roster_file(roster_mod.DEFAULT_PATH, changes)
        wrote = True
    return {
        "action": "enrich",
        "changes": diffs,
        "written": wrote,
        "path": str(roster_mod.DEFAULT_PATH) if wrote else None,
    }


def _fetch_page(url: str) -> str:
    """Fetch a blog homepage for github-link scraping. Small, bounded, silent on failure."""
    import requests

    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "cerebro-roster/1.0"})
    except requests.RequestException:
        return ""
    if r.status_code != 200:
        return ""
    return r.text[:262144]  # 256 KiB cap — homepage is enough for a profile link


def _roster_suggest(args, settings, devs, roster_mod) -> dict[str, Any]:
    known: set[str] = set()
    for dev in devs:
        known.add(dev.slug)
        if dev.github:
            known.add(dev.github.lower())
        if dev.x:
            known.add(dev.x.lower())
    candidates = _scan_developer_entities(getattr(settings, "vault_path", ""))
    picked = [c for c in candidates if c["login"].lower() not in known]
    picked.sort(key=lambda c: c["momentum_score"], reverse=True)
    picked = picked[: args.limit]
    return {
        "action": "suggest",
        "count": len(picked),
        "suggestions": picked,
        "yaml": _suggest_yaml_blocks(picked),
    }


def _scan_developer_entities(vault_path) -> list[dict[str, Any]]:
    """Read developer entity notes' frontmatter for suggest ranking. No network."""
    from pathlib import Path

    base = Path(vault_path) / "Entities" / "developers"
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for note in sorted(base.glob("*.md")):
        fm = _read_frontmatter(note.read_text(encoding="utf-8"))
        login = fm.get("login", "")
        if not login:
            continue
        try:
            momentum = float(fm.get("momentum_score") or 0.0)
        except (TypeError, ValueError):
            momentum = 0.0
        out.append({
            "login": login,
            "display_name": fm.get("display_name", ""),
            "profile_url": fm.get("profile_url", f"https://github.com/{login}"),
            "momentum_score": momentum,
        })
    return out


def _read_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"')
    return fm


def _suggest_yaml_blocks(candidates: list[dict[str, Any]]) -> str:
    blocks = []
    for c in candidates:
        blocks.append(
            f"  - name: {c['display_name'] or c['login']}\n"
            f"    tier: 3\n"
            f"    github: {c['login']}\n"
            f"    why: \"momentum_score={c['momentum_score']}\"\n"
            f"    discovered_via: suggest"
        )
    return "\n".join(blocks)


def _patch_roster_file(path, changes: list[tuple[str, str, str]]) -> None:
    """Set (dev_name, field, value) scalars in the roster YAML via a targeted line patch,
    preserving comments, key order, and every untouched line. Raises if a dev is missing."""
    from pathlib import Path

    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for dev_name, field_name, value in changes:
        _patch_one(lines, dev_name, field_name, value)
    path.write_text("".join(lines), encoding="utf-8")


def _patch_one(lines: list[str], dev_name: str, field_name: str, value: str) -> None:
    import re

    name_re = re.compile(r"^(\s*)-\s+name:\s*(.+?)\s*$")
    start = None
    list_indent = ""
    for i, line in enumerate(lines):
        m = name_re.match(line.rstrip("\n"))
        if m and m.group(2).strip().strip('"') == dev_name:
            start = i
            list_indent = m.group(1)
            break
    if start is None:
        raise ValueError(f"roster patch: dev {dev_name!r} not found")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].rstrip("\n")
        if not stripped.strip():
            continue
        cur_indent = len(stripped) - len(stripped.lstrip())
        if cur_indent <= len(list_indent):
            end = j
            break
    field_re = re.compile(rf"^(\s*){re.escape(field_name)}:\s*(.*?)(\s+#.*)?$")
    scalar = _yaml_scalar_out(value)
    for k in range(start, end):
        fm = field_re.match(lines[k].rstrip("\n"))
        if fm:
            newline = "\n" if lines[k].endswith("\n") else ""
            comment = fm.group(3) or ""
            lines[k] = f"{fm.group(1)}{field_name}: {scalar}{comment}{newline}"
            return
    lines.insert(start + 1, f"{list_indent}  {field_name}: {scalar}\n")


def _yaml_scalar_out(value: str) -> str:
    """Emit a YAML scalar. Quote only when a bare value would be ambiguous."""
    import re

    s = str(value)
    if s == "" or re.search(r'(^[\s\[\]{}#&*!|>%@`"\',])|(:\s)|(\s#)|(\s$)', s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


if __name__ == "__main__":
    main()
