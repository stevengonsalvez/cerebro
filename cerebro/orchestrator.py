from __future__ import annotations

import datetime

from .config import Settings
from .llm import claude, digest, triage
from .models import RunStats
from .process import dedup, extract, junkgate
from .sink import notify, vault
from .sources import SOURCES
from .state import State


def run(settings: Settings) -> tuple[RunStats, dict]:
    run_id = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    date = datetime.date.today().isoformat()
    state = State()

    # 1. fetch all enabled sources (per-source isolation; X failure noted, not fatal)
    raw, x_ok = [], True
    for name, cfg in settings.sources.items():
        if not cfg.get("enabled") or name not in SOURCES:
            continue
        try:
            got = SOURCES[name](cfg, settings)
            raw += got
            if name == "x" and not got:
                x_ok = False
            print(f"[src] {name:16} {len(got)}")
        except Exception as e:  # noqa: BLE001 — one bad source must not sink the run
            if name == "x":
                x_ok = False
            print(f"[warn] source {name} failed: {type(e).__name__}: {e}")

    st = RunStats(run_id=run_id, raw=len(raw), dry_run=settings.dry_run, x_ok=x_ok)

    # 2. funnel: junk-gate → dedup → triage → extract top-N → digest
    cand = dedup.dedupe(junkgate.filter(raw), state, settings.dedup_days)
    st.after_dedup = len(cand)
    meter = claude.new_meter()
    kept = triage.triage(cand, settings, meter=meter)
    st.after_triage = len(kept)
    top = kept[: settings.depth.get("max", 25)]
    extract.enrich(top)
    briefing = digest.digest(top, settings, meter=meter)
    st.digested = len(top)
    st.input_tokens, st.output_tokens = meter["input_tokens"], meter["output_tokens"]
    st.cache_read, st.cache_creation = meter["cache_read"], meter["cache_creation"]
    st.cost_usd, st.llm_calls = meter["cost_usd"], meter["calls"]

    # 3. write + remember (mark every candidate so tomorrow doesn't re-triage them) + notify
    paths = vault.write(date, briefing, top, settings, st)
    for s in cand:
        state.mark(s)
    notify.push(st, paths["daily"], settings)
    state.log_run(st)
    state.close()
    return st, paths
