# Specification: CEREBRO — Daily Signal Intelligence Pipeline

**Generated from:** in-conversation brainstorm + `/interview` (no prior plan file)
**Interview date:** 2026-06-15
**Version:** 1.0
**Codenames:** Project **CEREBRO** (scans the noise for signals matching your profile) · operator **Steverebro**

## Executive Summary

CEREBRO is a local-first, token-minimal daily pipeline that ingests raw tech signals (Gmail
newsletters, Hacker News, Reddit, GitHub Trending, RSS, X), filters them against a hyper-specific
interest matrix, and writes a clean "explain-to-me" briefing plus atomic, Dataview-queryable notes
into a Google-Drive-synced Obsidian vault. Runs daily at 07:00 via launchd on macOS. Filtering is
done cheaply by Haiku 4.5; the user-facing digest by Sonnet 4.6. Target cost ~$4–5/month.

## Master Flow

```
SOURCES (free)            PRE-FILTER (cheap)              LLM (paid, tiny)        SINK
┌──────────┐
│ Gmail    │─┐
│ HN       │ │  ┌─────────┐ ┌──────┐ ┌──────────┐   ┌────────┐  ┌──────────┐
│ Reddit   │ ├─▶│ fetch + │▶│dedup │▶│ lenient  │▶  │ Haiku  │▶ │ Sonnet   │
│ GH Trend │ │  │ extract │ │simhash│ │ junk-gate│   │  4.5   │  │   4.6    │
│ RSS      │ │  └─────────┘ └──────┘ │ (regex)  │   │ triage │  │ digest   │
│ X (bird) │─┘                       └──────────┘   │ JSON   │  │ top 15-25│
└──────────┘                            ▲ ~$0       │ score  │  └────┬─────┘
                                  kills spam/non-EN └────────┘       │
                                                     80% kill        ▼
   sched: launchd 07:00 daily                                 ┌─────────────┐
   secrets: Bitwarden machine acct (bws)                      │ Vault .md   │
   state: SQLite seen-hash, 14-day window                     │ daily +     │
   notify: ntfy push (count + link)                           │ atomic notes│
                                                              └─────────────┘
```

## Objectives

### Primary Goals
- Daily intelligence briefing of signals matching the 4-category interest matrix
- Token-minimal: heavy free pre-filtering, Haiku triage, Sonnet only for final digest
- Obsidian-ready output: frontmatter, wikilinks, Dataview-queryable
- Fully autonomous after setup; survives mac sleep via launchd catch-up

### Success Metrics
- Briefing of 15–25 high-relevance signals/day, ~5 min read
- LLM spend ≤ ~$5/month
- < 1 manual intervention/week (only when bird cookies expire)
- Zero duplicate signals within a 14-day window

## Scope

### In Scope (v1)
- Sources: Gmail newsletters, HN, Reddit, GitHub Trending, RSS, X-via-bird
- Pre-filter funnel: dedup → regex junk-gate → Haiku triage
- Sonnet "explain-to-me" digest
- Vault write: daily note + atomic signal notes
- launchd scheduling, ntfy notification, SQLite state
- Dry-run mode (scratch folder, no notify) for first runs

### Out of Scope (v1)
- AI video / voice / TTS audio digest (deferred)
- GitHub Actions cloud fallback (architecture stays idempotent to allow it later)
- Web dashboard / UI — vault IS the interface
- Multi-device beyond Google Drive sync

### Future Considerations
- Audio (TTS) digest for commute
- Batches API for 50% Haiku discount (async, once volume justifies)
- Cloud fallback for non-X sources via GitHub Actions
- Weekly Opus deep-synthesis note across the week's signals

## Technical Requirements

### Architecture Decisions
```
LOCAL-FIRST  ─ launchd primary; X cookies + vault + secrets all want the mac
IDEMPOTENT   ─ URL-hash filenames; re-runs never duplicate
FUNNEL       ─ cheapest stage first; LLM only touches survivors
SINGLE KEY   ─ script needs only ANTHROPIC_API_KEY; bird/gog hold own auth
```

### Components
| Component | Purpose | Technology |
|-----------|---------|------------|
| Scheduler | Fire daily 07:00, catch-up on wake | launchd plist (`StartCalendarInterval`) |
| Orchestrator | Run the funnel end-to-end | Python 3.x |
| Gmail ingest | Pull labeled/sender newsletters | `gog` skill (Gmail API) |
| HN ingest | Top + show stories | HN Firebase JSON API |
| Reddit ingest | Curated subreddit new/top | Reddit `.json` endpoints |
| GitHub Trending | Daily trending repos | trending scrape/JSON |
| RSS ingest | Curated feeds, skip-unchanged | feedparser + ETag/If-Modified-Since |
| X ingest | Search by tags + read accounts | `bird` CLI (read-only, burner acct) |
| Extractor | HTML → clean main text | trafilatura |
| Dedup | Cross-source near-dup kill | URL-canonical + simhash |
| Junk-gate | Lenient regex spam/non-EN cut | stdlib regex |
| Triage | Semantic relevance + tag score | Haiku 4.5, strict JSON output |
| Digest | "Explain-to-me" briefing | Sonnet 4.6 |
| State | Seen-hash, 14-day dedup window | SQLite |
| Sink | Write daily + atomic notes | Python file writes to vault |
| Notifier | Push when ready | ntfy |
| Secrets | Fetch API key at runtime | Bitwarden Secrets Manager (`bws`) |

### Integrations
- **Vault:** direct write to `/Users/stevengonsalvez/My Drive/mynotes` (Google Drive syncs it).
- **bird:** `bird search "<tag>" -n N`, `bird read`, `bird thread` — read-only, burner X account, cookie auth (residential IP). Sweetistics is a manual fallback engine.
- **gog:** Gmail API, query `(label:newsletters OR from:{senders}) newer_than:1d`.
- **Bitwarden:** `bws secret get` for `ANTHROPIC_API_KEY` (machine account). Bootstrap `BWS_ACCESS_TOKEN` lives in the launchd environment / Keychain.

### Interest Matrix (seeded, tune in `_meta/interest-matrix.yaml`)
| # | Category | Frontmatter tags | Focus |
|---|----------|------------------|-------|
| 1 | Coding Agents & LLM Mechanics | `ai/agents`, `ai/llm-mechanics`, `release-notes` | Claude/Codex/Copilot changelogs; token-opt, prompt-caching, context-window mgmt, agentic patterns |
| 2 | CLI & TUI Ecosystem | `cli/tui` | Terminal utilities, TUIs, workflow streamliners |
| 3 | Vibe Coding & Viral Repos | `vibe-coding`, `repo/trending` | Rising GitHub repos, viral AI frameworks, agent-driven build tools |
| 4 | Agentic Tool-Pairing & AI SaaS | `ai/saas`, `ai/tool-pairing` | Mission-control dashboards, multimodal extensions (video/voice/browser) |

### Source Config (seeded, tunable)
| Source | Seed config |
|--------|-------------|
| Subreddits | r/ClaudeAI, r/ChatGPTCoding, r/LocalLLaMA, r/AI_Agents, r/vibecoding, r/cursor |
| Newsletter senders | AI Breakfast, The Rundown, TLDR, Ben's Bites, ByteByteGo + `newsletters` label |
| HN | top + show stories |
| GitHub Trending | daily window, all languages (relevance handled downstream) |
| RSS | curated feed list (TBD — seed at first build) |
| X key accounts / tags | seeded from the 4 categories; tune in config |

### Performance / Cost
| Stage | Model | ~tokens/day | ~$/mo |
|-------|-------|-------------|-------|
| Triage | Haiku 4.5 | ~10k in / 2k out | ~0.60 |
| Digest | Sonnet 4.6 | ~20k in / 4k out | ~3.60 |
| Sources | — | — | 0 |
| **Total** | | | **~4–5** |

Prompt caching is moot at this volume (matrix likely < Haiku's 4096-token cache minimum; Haiku input ~$0.00001/day).

### Security Requirements
- No secrets on disk: `ANTHROPIC_API_KEY` fetched at runtime from Bitwarden machine account.
- bird uses a **burner** X account — automation never touches the main account.
- bird/gog auth tokens managed by those tools, outside the repo.
- `.env`, cookies, tokens gitignored.

## Operational Behaviour

### Daily Run Sequence
```
launchd 07:00 (catch-up if asleep)
   │
   ▼
fetch all sources ──▶ bird X-auth dead? ──▶ ntfy "X cookies expired" + skip X
   │
   ▼
dedup (simhash) ▶ regex junk-gate ▶ SQLite 14-day seen-filter
   │  (~80% gone, $0 spent)
   ▼
Haiku triage (batch, strict JSON score+tags) ──▶ top 15-25 survivors
   ▼
Sonnet "explain-to-me" digest
   ▼
write Daily/YYYY-MM-DD.md + Signals/<urlhash>.md  (or scratch/ in dry-run)
   ▼
ntfy push "briefing ready · N signals · <link>"  (suppressed in dry-run)
```

### Vault Layout
```
mynotes/
├── Cerebro/Daily/2026-06-15.md     # briefing, wikilinks → signals
├── Cerebro/Signals/<urlhash>.md    # atomic, Dataview frontmatter
└── Cerebro/_meta/interest-matrix.yaml
```
Signal frontmatter: `category`, `tags`, `source`, `url`, `score`, `captured`.

### Edge Cases
| Scenario | Expected behaviour |
|----------|--------------------|
| Mac asleep at 07:00 | launchd runs on next wake (catch-up) |
| bird cookies expired | ntfy alert + run completes without X |
| Same story HN + Reddit + newsletter | simhash collapses to one signal |
| Re-run same day | URL-hash filenames → idempotent, no dupes |
| Signal seen 5 days ago | suppressed by 14-day dedup window |
| RSS feed unchanged | ETag skip, no re-fetch |
| Source API down | log + continue with remaining sources |

## Decisions Made

### Key Trade-offs
| Decision | Alternatives considered | Rationale |
|----------|-------------------------|-----------|
| Local launchd | GitHub Actions, hybrid | X cookies + vault + secrets all need the mac; Actions' datacenter IP kills X scraping |
| bird for X | browser-harness, twikit, official API | Same author as browser-harness, installed, GraphQL-direct, reads 99.8% safe; browser-harness now fallback |
| Haiku filter | Ollama local embeddings | $1/1M is cheap enough to be the filter; drops the Ollama daemon/infra tax |
| Sonnet digest | Haiku (cheaper), Opus (premium) | Quality where the user reads; Haiku stays the cheap filter |
| Direct vault write | Git-repo sync | Vault is a local Drive-synced folder; direct write is zero-latency and offline |
| Burner X account | Main account | Ban-proof hygiene though reads are low-risk |

### Deferred Decisions
- RSS feed list — seed at first build, tune after.
- X key-account list — seed from matrix, tune after.
- TTS audio digest — future.
- Batches API for Haiku discount — future, once volume justifies.

## Risks & Mitigations
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| bird/X GraphQL breaks | Med | Med | Read-only + burner; Sweetistics manual fallback; ntfy alert |
| Google Drive online-only files | Low | Low | Ensure vault folder is "available offline"; script writes locally, Drive syncs |
| Regex gate under-filters | Low | Low | Gate is lenient by design; Haiku does real semantic cut |
| BWS_ACCESS_TOKEN bootstrap exposure | Med | Low | Token in launchd env / Keychain, not in repo |
| Haiku JSON malformed | Low | Low | Strict JSON schema + retry on parse fail |

## Implementation Notes

### Priority Order
1. Project scaffold + config files (`interest-matrix.yaml`, source config) + SQLite schema
2. Source ingestors (HN, Reddit, GitHub, RSS) — pure-JSON, fastest to verify
3. Gmail (gog) + bird (X) ingestors
4. Extract (trafilatura) + dedup (simhash) + regex junk-gate
5. Haiku triage (strict JSON) + Sonnet digest
6. Vault writer (daily + atomic notes, frontmatter)
7. ntfy notifier + launchd plist
8. Dry-run mode → eyeball output → flip to live

### Rollout
- **Dry-run first:** write to `Cerebro/_scratch/`, ntfy suppressed. Eyeball 1–2 days.
- **Go live:** point writer at real `Cerebro/`, enable ntfy, load launchd plist.

### Technical Debt Accepted
- RSS + X-account lists seeded, not curated — tune post-launch.
- No Batches API yet (synchronous Haiku) — pennies/month, optimize later.

## Open Questions
- [ ] Exact RSS feed URLs to seed
- [ ] X key accounts to follow via bird (beyond tag search)
- [ ] Confirm `mynotes` vault folder is set "available offline" in Google Drive
- [ ] Bitwarden secret key/ID name for `ANTHROPIC_API_KEY`

---

*Generated through systematic `/interview` of the CEREBRO brainstorm. Ready for `/plan`.*
