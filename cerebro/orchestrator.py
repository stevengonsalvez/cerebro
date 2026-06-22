from __future__ import annotations

import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import Settings
from .llm import claude, digest, triage
from .models import RunStats
from .process import comments, dedup, extract, feedback, junkgate, prerank
from .sink import notify, vault
from .sources import SOURCES
from .state import State


def run(settings: Settings) -> tuple[RunStats, dict]:
    run_id = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    date = datetime.date.today().isoformat()
    state = State()

    # 1. fetch all enabled sources concurrently (per-source isolation; X failure noted, not fatal)
    jobs = [(n, c) for n, c in settings.sources.items() if c.get("enabled") and n in SOURCES]

    def _run(name, cfg):
        try:
            return name, SOURCES[name](cfg, settings), None
        except Exception as e:  # noqa: BLE001 — one bad source must not sink the run
            return name, [], e

    raw, x_ok = [], True
    with ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as ex:
        for fut in as_completed([ex.submit(_run, n, c) for n, c in jobs]):
            name, got, err = fut.result()
            if err is not None:
                print(f"[warn] source {name} failed: {type(err).__name__}: {err}")
                if name == "x":
                    x_ok = False
                continue
            raw += got
            print(f"[src] {name:16} {len(got)}")
            if name == "x" and not got:
                x_ok = False

    st = RunStats(run_id=run_id, raw=len(raw), dry_run=settings.dry_run, x_ok=x_ok)

    # 2. funnel: junk-gate → dedup → triage → extract top-N → digest
    profile = feedback.load_profile(settings)   # learned from your rated vault notes
    if profile["n"]:
        print(f"[feedback] profile from {profile['n']} rated notes")
    cand = dedup.dedupe(junkgate.filter(raw), state, settings.dedup_days)
    st.after_dedup = len(cand)
    ranked = prerank.prerank(cand, settings, settings.prerank_keep, profile)
    print(f"[prerank] {len(cand)} → {len(ranked)} to triage")
    meter = claude.new_meter()
    kept = triage.triage(ranked, settings, meter=meter, profile=profile)
    st.after_triage = len(kept)
    top = kept[: settings.depth.get("max", 25)]
    extract.enrich(top)
    comments.enrich(top, settings, meter=meter)   # HN community take on the top-N
    briefing = digest.digest(top, settings, meter=meter)
    st.digested = len(top)
    st.input_tokens, st.output_tokens = meter["input_tokens"], meter["output_tokens"]
    st.cache_read, st.cache_creation = meter["cache_read"], meter["cache_creation"]
    st.cost_usd, st.llm_calls = meter["cost_usd"], meter["calls"]

    # 3. write + remember (mark every candidate so tomorrow doesn't re-triage them) + notify
    paths = vault.write(date, briefing, top, settings, st)
    for s in ranked:        # mark only LLM-evaluated items; pre-rank-dropped tail re-evaluates cheaply tomorrow
        state.mark(s)
    notify.push(st, paths["daily"], settings)
    state.log_run(st)
    state.close()
    return st, paths
