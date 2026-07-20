# Specification: Cracked-Dev Auto-Discovery (crackscan)

**Generated from:** interview (raw idea, no prior plan file)
**Interview date:** 2026-07-20
**Version:** 1.0

## Executive Summary

Today we identify rising *repos* (`github_trending` + `ossinsight` star-velocity,
`gitintel/metrics.py` momentum). We do **not** symmetrically identify rising *humans*.
This adds a `crackscan` source that resolves candidate humans from four seed pools,
scores their "crackedness" (commit rate, follower growth, portfolio momentum, output),
and auto-admits high scorers to the roster as tier 3 — bounded by a two-stage cost funnel
and a hard human/org/bot filter.

## Objectives

### Primary Goals
- Symmetric to star-scan: hot signal → find the builder → assess the builder → track them.
- Reuse the existing dev-scoring spine (`enrich_user_metrics`, `portfolio_momentum`) — do not rebuild.
- Auto-grow the roster's tier-3 tail without hand-curation, keeping tier 1/2 human-owned.

### Success Metrics
- Every scan: candidates resolved, scored, top-N deep-assessed, ≤N auto-admitted.
- Zero orgs/bots admitted (human filter holds).
- Commit-rate deep pass stays inside a dedicated rate-limit budget (never starves the digest).

## Scope

### In Scope — full slice (MVP = the whole thing, per interview)
- 4 discovery seeds, human filter, two-stage score, auto-add tier 3, dedicated token.

### Out of Scope
- No LLM in the discovery/scoring path — deterministic metrics only.
- No auto-admission to tier 1/2 — crackscan only ever writes tier 3.
- No promotion logic (tier 3 → tier 1). Human edits YAML to promote.
- No scraping X/Reddit *profiles* — identity only via github's own `twitter_username` + `identity.py`.

### Future Considerations
- Promotion suggestions (tier-3 dev sustains momentum → propose tier bump).
- Contributor-graph clustering (cracked devs co-commit) as a 5th seed weight.

## Technical Requirements

### Architecture — two-stage funnel, piggybacks main scan

```
┌───────────── SEEDS (candidate humans) ───────────────┐
│ 1 hot repos  → owner / top-committer                 │
│ 2 vault repo notes → owner                           │
│ 3 reddit/x authors → github (identity.py, medium+)   │
│ 4 contributors of roster repos                       │
└───────────────────────┬──────────────────────────────┘
                        ▼  dedup by login
              ┌──────────────────┐
              │  HUMAN FILTER    │  drop org/bot/empty
              └────────┬─────────┘
                        ▼
        ┌──────────────────────────────┐  CHEAP score (cached payload +
        │ STAGE A: cheap-score ALL     │  follower snapshots + portfolio)
        └────────────┬─────────────────┘  no per-commit calls
                      ▼ rank, take top-N
        ┌──────────────────────────────┐  DEEP: events API 90d commit-rate
        │ STAGE B: deep-score top-N    │  token B (GITHUB_TOKEN_CRACKSCAN)
        └────────────┬─────────────────┘
                      ▼  final crackedness score
        ┌──────────────────────────────┐
        │ ADMIT: score≥thr, max N/scan │→ tier 3, discovered_via: crackscan
        │ rest → logged 'considered'   │  (rest not admitted, just recorded)
        └──────────────────────────────┘
```

### Components
| Component | Purpose | Notes |
|---|---|---|
| `cerebro/sources/crackscan.py` | new source: seeds→filter→score→admit | `fetch(cfg, settings)` contract; piggybacks orchestrator |
| owner resolver | repo full_name → human login | org-owned → top human committer (`/repos/{r}/contributors`) |
| human filter | reject org/bot/empty | `type != User`, `[bot]` suffix, vendor denylist, require name\|bio |
| cheap scorer | Stage A | reuse `enrich_user_metrics` + `portfolio_momentum`, cached payload |
| deep scorer | Stage B commit-rate | `/users/{u}/events` PushEvent count / 90d, top-N only |
| admitter | write tier-3 to `cracked_devs.yaml` | line-level append (comment-safe), dedup by `slug`, cap N |
| `github_client` token override | per-source token | read `cfg.token_env` → `GITHUB_TOKEN_CRACKSCAN`, fallback `GITHUB_TOKEN` |

### Crackedness score (final)
| Signal | Source | Cost | Weight (tunable) |
|---|---|---|---|
| commit rate/day (90d PushEvents) | events API | deep, top-N only | 0.35 |
| follower growth 7d/30d | `enrich_user_metrics` snapshots | cheap | 0.25 |
| portfolio momentum | `portfolio_momentum()` | medium (their repos) | 0.25 |
| ships-a-lot proxy (public_repos + push recency + acct age) | cached payload | free | 0.15 |

> Stage A scores on the cheap three (follower/portfolio/ships); commit-rate folds in only
> for the top-N that survive to Stage B. Non-deep candidates keep their Stage-A score.

### Integrations
- Orchestrator: registered in `SOURCES`, runs every scheduled scan, inherits per-source error isolation.
- Roster: writes tier-3 entries `apply_to_sources` then wires (tier 3 = tracked, **unwired** by `max_tier`).
- Config: `crackscan:` block in `sources.yaml`; `token_env`, `top_n`, `admit_max`, `score_threshold`, `window_days`.

### Performance / rate-limit
- Dedicated token B: isolates deep-pass burn, +5000/hr ceiling.
- Stage A: ~1 cached call/candidate (mostly cache hits). Stage B: 1 events call × top-N (~10) per scan.
- Budget guard: if token B < K remaining, skip Stage B this scan (Stage-A scores still admit).

### Security
- Token B stored in Bitwarden (`cerebro_env` note or new item), read via `token_env`. Never committed.
- Vendor denylist + `type` check prevent org account takeover polluting roster.

## User Experience

### Flows
1. **Scheduled scan** → crackscan runs silently → 0–N new tier-3 devs appear in `cracked_devs.yaml` with `discovered_via: crackscan`, `why: "crackscore=0.xx; commits/day=N; +F followers/30d"`.
2. **Review** → `roster list --tier 3 --discovered crackscan` → prune bad admits by deleting lines.
3. **Promote** → edit tier 3→1 by hand (crackscan never promotes).

### Edge Cases
| Scenario | Behavior |
|---|---|
| Repo owner is org | resolve top human committer instead; if none human → skip |
| Candidate already on roster (any tier) | dedup by `slug`, never re-add, never churn |
| Bot / `[bot]` / vendor org | filtered pre-score, never admitted |
| reddit/x author, low identity confidence | rejected (require medium+); logged as unresolved |
| Token B unset | fall back to `GITHUB_TOKEN`; log the fallback |
| Token B rate-limited mid-scan | skip Stage B, admit on Stage-A scores only |
| Empty account (no name/bio) | fails human-signal filter, skipped |
| Quiet day, nobody ≥ threshold | admit nobody (score gate, not top-N-regardless) |

## Constraints & Dependencies

### Technical Constraints
- events API = public activity only (private commits invisible) — acceptable, cracked ≈ public output.
- No per-scan cap breach: `admit_max` (~5) hard-caps roster growth/scan; rest logged not written.
- Line-level YAML append must preserve existing comments/order (same constraint as `roster enrich --write`).

### External Dependencies
- Second GitHub account + token (Stevie provides, stores in Bitwarden).
- `identity.py` (shipped) for seed 3.
- `metrics.py` `enrich_user_metrics` + `portfolio_momentum` (shipped).

### Timeline
- Single build, no phased check-in (interview chose full auto-add as MVP).

## Risks & Mitigations
| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Org/bot pollution of roster | Med | High w/o filter | 4-layer human filter (type, [bot], denylist, human-signal) |
| Rate-limit exhaustion | High | Med | dedicated token B + two-stage funnel + budget guard skip |
| Roster churn / flapping | Med | Med | dedup by slug; score≥threshold; admit_max cap/scan |
| Wrong identity (seed 3) | Low | Med | require medium+ confidence; tier 3 is low-stakes + prunable |
| events API 90d misses burst devs | Low | Low | follower + portfolio momentum cover recent risers independently |
| github/trending HTML drift | Low | Med | seed degrades gracefully; ossinsight + vault seeds still feed |

## Decisions Made

### Key Trade-offs
- **Auto-add tier 3** (not suggest-only): chosen deliberately — breaks the original roster's
  "no auto-admission" rule. Justified because tier 3 is *tracked-but-unwired* (`max_tier` gate),
  so a bad admit costs nothing until a human promotes it. Alternatives (suggest-only, separate
  watchlist) rejected as too much manual friction for the tail.
- **Dedicated token B**: isolation + 2x ceiling. Rejected shared-token as it risks starving the digest.
- **Bounded funnel** (cheap-all → deep top-N): commit-rate is the only expensive signal; funnel keeps
  it affordable. Rejected generous (per-candidate history) as rate-limit exposure.
- **Commit-rate via events API 90d**: one call/candidate, standard. Rejected contribution-scrape (brittle)
  and per-repo commit lists (call-explosion).
- **Piggyback main scan**: candidates flow with every scan; deep pass is cheap enough under token B.

### Deferred
- Tier-3→1 promotion suggestions.
- Contributor-cluster weighting.

## Implementation Notes

### Priority Order
1. `github_client` per-source `token_env` override (+ fallback) — unblocks isolation.
2. Owner/top-committer resolver + human filter (the correctness core).
3. Stage-A cheap scorer wired to existing metrics.
4. Stage-B events-API commit-rate + budget guard.
5. Admitter: dedup-by-slug, score gate, admit_max cap, comment-safe YAML append.
6. `crackscan` source registration + `sources.yaml` block + tests.

### Technical Debt Accepted
- events API = public-only commit visibility (documented, acceptable).
- Vendor denylist is hand-maintained (grows as false-admits appear).

## Open Questions
- [ ] `score_threshold` and `admit_max` starting values — tune after first live scan (suggest thr=0.55, admit_max=5).
- [ ] Token B: new Bitwarden item vs append to `cerebro_env` note — decide at secret-store time.
- [ ] Seed weighting — are all 4 seeds equal, or does "contributor of roster repo" rank higher (cracked cluster)?

---

*Generated through structured interview. Ready for `/plan` to turn into a waved implementation plan.*
