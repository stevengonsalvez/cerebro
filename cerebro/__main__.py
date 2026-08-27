from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import __version__
from .process import weekly as weekly_defaults


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
    cd_roster.add_argument("--discovered", default=None,
                           help="list: filter to devs discovered via this source (e.g. crackscan)")
    cd_roster.add_argument("--write", action="store_true",
                           help="write enrichment back to config/cracked_devs.yaml")
    cd_roster.add_argument("--overwrite", action="store_true",
                           help="let resolution replace curated values (default: fill blanks only)")
    cd_roster.add_argument("--limit", type=int, default=20, help="suggest: max candidates")

    serve = sub.add_parser("serve", help="serve local Cerebro UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=4317)

    rp = sub.add_parser("roundup", help="write the deterministic weekly roundup note (no LLM)")
    rp.add_argument("--week", default=None,
                    help="ISO week, e.g. 2026-w33 (default: last complete week)")
    rp.add_argument("--top-n", type=int, default=weekly_defaults.TOP_N)
    rp.add_argument("--per-source-cap", type=int, default=weekly_defaults.PER_SOURCE_CAP)
    rp.add_argument("--per-category-cap", type=int, default=weekly_defaults.PER_CATEGORY_CAP)
    rp.add_argument("--force", action="store_true", help="overwrite an existing weekly note")
    mx = rp.add_mutually_exclusive_group()
    mx.add_argument("--dry-run", action="store_true",
                    help="force a dry run: write to _scratch/Weekly/")
    mx.add_argument("--write", action="store_true",
                    help="force a real write to Weekly/ regardless of settings.dry_run "
                         "(honours $CEREBRO_VAULT — point it at a copy, never at the live vault)")

    ds = sub.add_parser("devs-spike",
                        help="F066 sanity gate: dry-run the vault-lane devs pipeline "
                             "and write an eyeballable top-20 (writes nothing to the vault)")
    ds.add_argument("--dry-run", action="store_true", required=True,
                    help="the only supported mode; a live mode is not implemented")
    ds.add_argument("--out", default=".agents/scratch/",
                    help="directory for the top-20, flag queue, run json and query bytes")
    ds.add_argument("--vault", default=None,
                    help="corpus to mine (default: settings.vault_path, read-only either way)")
    ds.add_argument("--verdicts", default=None,
                    help="path to the quality verdicts file")
    ds.add_argument("--limit", type=int, default=20)
    ds.add_argument("--lanes", default="vault,fanout,roster",
                    help="comma-separated discovery lanes: vault, fanout, roster "
                         "(default: all three)")
    ds.add_argument("--fanout-repos", type=int, default=60,
                    help="seed repos the contributor fan-out reads, in signal-recurrence "
                         "order; page 1 only, 1 REST call each (default: 60)")
    ds.add_argument("--rest-budget", type=int, default=1400,
                    help="hard cap on humanness pre-filter REST calls. Measured "
                         "2026-08-27: 60 seed repos surface 2,452 contributors, 1,252 of "
                         "which clear the activity floor and need the call. The overflow "
                         "is recorded, and an unchecked account reaching the top list "
                         "FAILS the sanity gate (default: 1400)")
    ds.add_argument("--fork-budget", type=int, default=300,
                    help="hard cap on TOTAL fork-provenance REST calls for the run, "
                         "shared across every flagged candidate. On exhaustion the "
                         "remaining flags stand UNEVIDENCED; a budget running out never "
                         "clears anybody (default: 300)")

    dr = sub.add_parser(
        "devs-refresh",
        help="write the Devs/ corpus from the devs pool (opt-out gated, "
             "reconciling; dry-run writes to _scratch/Devs/)")
    dr_mx = dr.add_mutually_exclusive_group()
    dr_mx.add_argument("--dry-run", action="store_true",
                       help="force a dry run: write to _scratch/Devs/")
    dr_mx.add_argument("--write", action="store_true",
                       help="force a real write to Devs/ regardless of settings.dry_run")
    dr.add_argument("--out", default=None,
                    help="artifact directory (default: logs/devs/<date>/, gitignored, "
                         "never the vault)")
    dr.add_argument("--vault", default=None,
                    help="corpus to mine AND write into (default: settings.vault_path). "
                         "The Signals/ corpus the pool is mined from is not in every "
                         "checkout; point this at one that has it or the pool is empty")
    dr.add_argument("--optout", default=None,
                    help="path to the CONSENT file (default: config/devs_optout.yaml)")
    dr.add_argument("--verdicts", default=None,
                    help="path to the QUALITY verdicts file (a different file, always)")
    dr.add_argument("--limit", type=int, default=20,
                    help="rows in the eyeball top list (not a cap on the corpus)")
    dr.add_argument("--lanes", default="vault,fanout,roster")
    dr.add_argument("--fanout-repos", type=int, default=60)
    dr.add_argument("--rest-budget", type=int, default=1400)
    dr.add_argument("--fork-budget", type=int, default=300)
    dr.add_argument("--repo-budget", type=int, default=500,
                    help="hard cap on TOTAL repos[] REST calls for the run, shared "
                         "across the publish set and spent in signal-recurrence order. "
                         "Devs the cap does not reach keep repos_populated: false and "
                         "render no repo card (default: 500)")

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

    if args.command == "roundup":
        # Deliberately handled BEFORE `from .orchestrator import run` below: the roundup
        # is a pure, LLM-free re-read of notes the vault already holds, and returning
        # from here makes it structurally incapable of triggering a pipeline run.
        import datetime as _datetime

        from .process import weekly
        from .sink import roundup as roundup_sink, vault_read

        # Tri-state dry-run. --dry-run forces a scratch write, --write forces a real one,
        # and NEITHER defers to config/settings.yaml — which is what run.sh relies on, so
        # the no-flag form must stay `None` rather than being coerced to a bool.
        dry_override = True if args.dry_run else (False if args.write else None)
        settings = load(dry_run_override=dry_override, allow_example=True)
        read = vault_read.read_signal_notes(settings.vault_path)
        week = (
            weekly.parse_week(args.week) if args.week
            else weekly.last_complete_week(_datetime.date.today())
        )
        selection = weekly.select(
            read.notes, week,
            top_n=args.top_n,
            per_source_cap=args.per_source_cap,
            per_category_cap=args.per_category_cap,
        )
        result = roundup_sink.write(selection, settings, force=args.force)
        # `dry_run` rides along so a reader of the JSON can tell which of the two roots
        # `path` sits under without re-deriving it from the settings.
        result["dry_run"] = settings.dry_run
        result["notes_read"] = len(read.notes)
        result["notes_skipped"] = read.skipped
        print(json.dumps(result, indent=2))
        return

    if args.command == "devs-spike":
        # Handled BEFORE `from .orchestrator import run`: the spike is a dry-run read of
        # the vault plus a free ClickHouse query, and returning from here makes it
        # structurally incapable of triggering a pipeline run. It emits zero Signals.
        import sys

        from .gitintel import denylist as _denylist, devs_spike
        from .gitintel.github_client import GitHubClient, resolve_token

        settings = load(dry_run_override=True, allow_example=True)
        vault = args.vault or settings.vault_path
        crackscan_cfg = (settings.sources or {}).get("crackscan", {})
        client = GitHubClient(settings, token=resolve_token(crackscan_cfg, settings))
        lanes = tuple(x.strip().lower() for x in (args.lanes or "").split(",") if x.strip())
        unknown = [x for x in lanes if x not in devs_spike.LANES]
        if unknown:
            raise SystemExit(f"unknown lane(s) {unknown}; choose from {devs_spike.LANES}")
        result, top, records, paths = devs_spike.run(
            vault, args.out, client=client,
            verdicts_path=args.verdicts or _denylist.DEFAULT_PATH,
            limit=args.limit,
            lanes=lanes,
            fanout_repos=args.fanout_repos,
            rest_budget=args.rest_budget,
            fork_budget=args.fork_budget,
        )
        print()
        print(f"top-{len(top)} written to {paths['top']}  (artifact-hash {paths['hash']})")
        print(f"flag queue      {paths['queue']}")
        print(f"lane census     {paths['census']}")
        print(f"budget report   {paths['budget']}")
        print(f"run json        {paths['json']}")
        for w in result.warnings:
            print(f"WARNING: {w}")
        if not result.ok:
            for f in result.failures:
                print(f"  {f}")
            print("SANITY GATE FAILED — SHIP NOTHING")
            sys.exit(1)
        print("SANITY GATE: mechanical predicate GREEN "
              "(zero bots, zero vendor orgs, zero denied logins, zero unresolved flags)")
        print("The eyeball is NOT optional: the predicate only tests for shapes already "
              "known.")
        return

    if args.command == "devs-refresh":
        # Handled BEFORE `from .orchestrator import run`, exactly like `roundup` and
        # `devs-spike`, so this stage is STRUCTURALLY INCAPABLE of triggering a pipeline
        # run. run.sh calls it after the roundup and before `git add`, soft-failing.
        import datetime as _datetime
        import sys

        from .gitintel import denylist as _denylist, devs_spike, optout as _optout
        from .gitintel import repo_facts as _repo_facts
        from .gitintel.cache import GitIntelCache
        from .gitintel.github_client import GitHubClient, resolve_token
        from .sink import devs as devs_sink

        stamp = _datetime.date.today().isoformat()
        out_dir = Path(args.out) if args.out else Path("logs") / "devs" / stamp
        out_dir.mkdir(parents=True, exist_ok=True)

        # Tri-state dry-run, same rule as the roundup: NEITHER flag defers to
        # config/settings.yaml, which is what run.sh relies on.
        dry_override = True if args.dry_run else (False if args.write else None)
        settings = load(dry_run_override=dry_override, allow_example=True)
        vault = args.vault or settings.vault_path
        optout_path = args.optout or _optout.DEFAULT_PATH
        verdicts_path = args.verdicts or _denylist.DEFAULT_PATH

        # FAIL CLOSED, AND FAIL FIRST. A malformed consent file exits non-zero here,
        # before a single query is rendered or a single call is spent. Returning
        # unfiltered candidates because the file could not be parsed would publish a
        # person who asked to be removed.
        try:
            consent = _optout.load(optout_path)
        except ValueError as exc:
            print(f"OPT-OUT FILE UNREADABLE — NOTHING WAS WRITTEN\n  {exc}")
            sys.exit(2)
        verdicts = _denylist.load(verdicts_path)

        crackscan_cfg = (settings.sources or {}).get("crackscan", {})
        token = resolve_token(crackscan_cfg, settings)
        client = GitHubClient(settings, token=token)
        # THE SECOND CLIENT, AND THE WHOLE REASON THE REPO LANE IS AFFORDABLE. Repo
        # metadata does not change hourly; a 24h TTL would re-buy the entire corpus every
        # morning for nothing.
        gh_cfg = getattr(settings, "github", {}) or {}
        repo_client = GitHubClient(settings, token=token, cache=GitIntelCache(
            gh_cfg.get("cache_path"), _repo_facts.REPO_CACHE_TTL_HOURS))

        lanes = tuple(x.strip().lower() for x in (args.lanes or "").split(",") if x.strip())
        unknown = [x for x in lanes if x not in devs_spike.LANES]
        if unknown:
            raise SystemExit(f"unknown lane(s) {unknown}; choose from {devs_spike.LANES}")

        result, top, records, paths = devs_spike.run(
            vault, out_dir, client=client, verdicts_path=verdicts_path,
            optout_path=optout_path, limit=args.limit, lanes=lanes,
            fanout_repos=args.fanout_repos, rest_budget=args.rest_budget,
            fork_budget=args.fork_budget, repo_budget=args.repo_budget,
            repo_client=repo_client, stage="devs-refresh")

        for w in result.warnings:
            print(f"WARNING: {w}")
        if not result.ok:
            # SHIP NOTHING. Not a partial corpus, not yesterday's corpus with today's
            # additions — nothing. The artifacts stay for the operator to read.
            for f in result.failures:
                print(f"  {f}")
            print("SANITY GATE FAILED — NOTHING WAS WRITTEN")
            sys.exit(1)

        budget = json.loads(Path(paths["budget"]).read_text(encoding="utf-8"))
        # HEALTHY, and every term is a way the run can be WRONG rather than merely small.
        # A truncated REST budget means accounts nobody checked; a missing ClickHouse scan
        # means windows nobody measured. Either one makes today's absences untrustworthy,
        # and an untrustworthy absence must not unpublish a real person.
        #
        # `rest_failures` IS THE TERM FOR A DEGRADED LANE RATHER THAN A SMALL ONE, and it
        # is not covered by any other term here. Measured, not hypothesised: re-running
        # this stage with no token against the 1,036-note corpus logged 273 `resolve
        # failed ... GitHub 403 ... API rate limit exceeded` lines, published 31 of 1,316,
        # and set NOTHING else in this conjunction — `truncated` stays false because the
        # budget was never exhausted (the calls were made and refused), the ClickHouse
        # lane needs no token, and `records` was non-empty. Only the churn cap stood
        # between that run and deleting real people, and a smaller degradation slips
        # under the cap.
        #
        # ANY failure, not a threshold. The consequence of a false positive is that
        # today's churn deletions wait for tomorrow; the consequence of a false negative
        # is deleting a note about a named human because GitHub was busy.
        healthy = (result.ok
                   and not budget.get("truncated")
                   and not budget.get("rest_failures")
                   and budget.get("clickhouse_scans") == len(devs_spike.WINDOWS)
                   and bool(records))

        corpus_plan, written = devs_sink.write_corpus(
            records, settings, vault_path=vault, optout=consent, verdicts=verdicts,
            healthy=healthy)

        report = out_dir / f"devs-withheld-{stamp}.md"
        report.write_text(_withheld_report(corpus_plan, stamp, healthy),
                          encoding="utf-8")

        summary = {
            "stage": "devs-refresh",
            "dry_run": bool(settings.dry_run),
            "healthy": healthy,
            # Beside `healthy` rather than only in the budget artifact, because this is
            # the number that explains a `false` an operator is reading at 07:05.
            "rest_failures": int(budget.get("rest_failures") or 0),
            "pool": len(records),
            "published": len(corpus_plan.writes),
            "withheld": len(corpus_plan.withheld),
            "written": len(written["written"]),
            "unchanged": len(written["unchanged"]),
            "deleted_consent": len(corpus_plan.deletes_consent),
            "deleted_churn": len(corpus_plan.deletes_churn),
            "refused_reason": corpus_plan.refused_reason,
            "corpus_dir": written["dir"],
            "artifacts": {k: str(v) for k, v in paths.items() if k != "sql"},
            "withheld_report": str(report),
        }
        print(json.dumps(summary, indent=2))
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
        if args.discovered is not None:
            shown = [d for d in shown if d.discovered_via == args.discovered]
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
            f"  - name: {_yaml_scalar_out(c['display_name'] or c['login'])}\n"
            f"    tier: 3\n"
            f"    github: {_yaml_scalar_out(c['login'])}\n"
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


def _withheld_report(corpus_plan, stamp: str, healthy: bool) -> str:
    """THE AUDIT TRAIL FOR EVERYBODY THE WRITE GATE HELD BACK.

    `cerebro-vault` is PUBLIC, so a withheld person's record is NOT WRITTEN — which means
    the only place their absence is legible is here, in `logs/devs/` (gitignored, never
    the vault). Every withheld login is named with the clause it failed and the remedy,
    because "we withheld 1,193 people" is not transparency and a silent absence is
    indistinguishable from a bug.

    It describes what the pipeline did. It says nothing about any person.
    """
    from .sink import devs as devs_sink

    remedies = {
        devs_sink.REASON_PROVENANCE:
            "no vault Signal note cites this login or a repo they own, so the profile "
            "could not answer 'why is this person here'. The remedy needs no code: the "
            "moment any Signal note cites them, they publish on the next run.",
        devs_sink.REASON_OPTED_OUT:
            "this person asked to be removed. There is no remedy and none is wanted; "
            "any note already on disk was deleted in the same run.",
        devs_sink.REASON_DENIED:
            "a recorded verdict in config/devs_denylist.yaml excludes this account. "
            "Reversing it is an edit to that file by a reviewer, never an edit here.",
        devs_sink.REASON_NOT_ADMITTED:
            "an admission floor failed. The per-floor audit lines are on the record in "
            "the run json.",
    }
    groups: dict[str, list[str]] = {}
    for login, reason in corpus_plan.withheld:
        groups.setdefault(reason, []).append(login)

    lines = [
        f"# devs withheld — {stamp}",
        "",
        "THE WRITE GATE IS THE PUBLISH GATE. Nothing below was written into the vault,",
        "because the vault is a public repository and a written record is published data",
        "about a named human whether or not a page renders from it. This file is the",
        "operator's audit trail and lives under gitignored `logs/`.",
        "",
        f"run health: {'healthy' if healthy else 'DEGRADED — churn deletions refused'}",
        f"published: {len(corpus_plan.writes)}   withheld: {len(corpus_plan.withheld)}",
        f"deletions: {len(corpus_plan.deletes_consent)} consent, "
        f"{len(corpus_plan.deletes_churn)} churn"
        + (f" (REFUSED: {corpus_plan.refused_reason})"
           if corpus_plan.refused_reason else ""),
        "",
    ]
    for reason in sorted(groups, key=lambda r: (-len(groups[r]), r)):
        logins = sorted(groups[reason], key=str.lower)
        lines += [f"## {reason} — {len(logins)}", ""]
        remedy = next((v for k, v in remedies.items() if reason.startswith(k)), "")
        if not remedy and reason.startswith("prefilter:"):
            remedy = ("a humanness call was intended and never made. Raise "
                      "`--rest-budget` and re-run; nobody is suppressed by this.")
        if not remedy and reason.startswith("automation:"):
            remedy = ("a shape fired and no verdict resolves it. The paste-ready blocks "
                      "in the flag queue artifact are both directions of that decision.")
        if remedy:
            lines += [remedy, ""]
        lines += [f"- {x}" for x in logins]
        lines.append("")
    if not groups:
        lines.append("_(nothing was withheld)_")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
