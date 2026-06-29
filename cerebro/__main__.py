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
    from .sink import briefs, entities

    profile = result.get("profile") or {}
    written: list[dict[str, Any]] = []
    if write_entity:
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


if __name__ == "__main__":
    main()
