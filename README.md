# CEREBRO 🧠📡

> Scans the noise for the signals matching your profile.
> A local-first, token-minimal daily tech-intelligence pipeline → Obsidian.

<p align="center">
  <img src="docs/architecture.svg" alt="CEREBRO — daily tech-signal pipeline: 10 sources through fetch, dedup, pre-rank, Haiku triage, comment-enrich, Sonnet digest, into an Obsidian vault, with a feedback loop" width="100%">
</p>

> 📖 **Read the explainer:** [explainers.stevengonsalvez.com/cerebro](https://explainers.stevengonsalvez.com/cerebro/) — architecture, sources, signals, and the full pipeline in one page.

CEREBRO ingests raw tech signals from eleven channels — Hacker News (front-page, **Show HN**,
**Launch HN**), **YC RFS**, Reddit, GitHub Trending, OSSInsight, RSS, pinned seed URLs, Gmail newsletters, and
X — filters them against a hyper-specific interest matrix, and writes a clean
**"explain-to-me" briefing** plus atomic, Dataview-queryable notes into an Obsidian vault —
every day at 07:00 via `launchd`. The cheap filtering pass runs on Claude Haiku; the readable
digest on Claude Sonnet. **No API keys** — it drives Claude Code on the machine. Target:
~10 min/run, covered by your Claude Code subscription.

## Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12 |
| LLM | **Claude Code** CLI (`claude -p`) — no API key, uses its own login |
| ↳ triage model | `--model haiku` → `claude-haiku-4-5-20251001` (cheap, batched JSON scoring) |
| ↳ digest model | `--model sonnet` → `claude-sonnet-4-6` (the user-facing briefing) |
| Hacker News | Algolia search API (`front_page`) |
| Show HN | Algolia `show_hn` — own `showcase` channel (maker launches/demos) |
| Launch HN | Algolia `query="Launch HN"` — YC company launches + batch tag (W25/S25/P26) |
| YC RFS | scrape of `ycombinator.com/rfs` — the ideas YC wants funded |
| Reddit | per-subreddit RSS via `feedparser` (the `.json` API 403s unauth) |
| GitHub Trending | scrape of `github.com/trending` (daily + weekly windows) |
| OSSInsight | `api.ossinsight.io` REST — star-velocity (most stars gained in window) |
| RSS | `feedparser` over 10 curated feeds |
| Gmail | `gws` CLI (Google Workspace, own OAuth) |
| X / Twitter | `twscrape` — free, headless, **your saved Firefox cookies** (no API key) |
| Extract | `trafilatura` (HTML → clean text) |
| Dedup | `sha256` URL-hash + 63-bit simhash (stdlib) |
| State | SQLite (stdlib) — `seen` (dedup) + `runs` (stats + tokens) |
| Scheduler | `launchd` (07:00, catch-up on wake) |
| Notify | `ntfy` via `curl` |
| Output | Obsidian Markdown + Dataview frontmatter |
| Security | gitleaks + GitGuardian (pre-commit + CI), no secrets in repo |

## How it works

```
7 sources ─▶ fetch ─▶ junk-gate ─▶ dedup(+watermark) ─▶ pre-rank ─▶ Haiku triage
   (concurrent)                                             ▲           │ keep ≥ 0.5
                                            feedback ───────┘           ▼
   Obsidian vault ◀─ Sonnet digest ◀─ HN comment-enrich ◀─ extract ◀─ top 25
        │ you rate 1-5                                       (top 25)
        └──▶ feedback: preference profile, fed back into pre-rank + triage next run
```

| Stage | What it does | Code |
|-------|--------------|------|
| **fetch** | every source runs concurrently, each in its own try/except; X & Gmail skip gracefully if unavailable; everything normalizes to a `Signal` dataclass | `sources/*.py` |
| **junk-gate** | lenient — drops empty / mostly-non-English titles only. Real relevance is the triage pass (cheap enough to over-feed) | `process/junkgate.py` |
| **dedup + watermark** | see [Watermark](#watermark) below | `process/dedup.py` |
| **pre-rank** | pure-software gate (no LLM): scores each candidate on interest-matrix term overlap ± learned [feedback](#feedback), keeps the top `prerank_keep` (180). Roughly halves what triage pays for | `process/prerank.py` |
| **triage** | one `claude -p --model haiku` call per ~60 candidates; returns strict JSON `{score, category, tags, reason}` scored against the interest matrix + your feedback; keep `score ≥ 0.5`, sort | `llm/triage.py` |
| **extract** | `trafilatura` fetches + cleans the top-N pages (expensive, so post-triage only) | `process/extract.py` |
| **comment-enrich** | for HN items, one batched Haiku call summarizes the discussion into a "Community take" on the note | `process/comments.py` |
| **digest** | one `claude -p --model sonnet` call → themed "explain-to-me" Markdown briefing | `llm/digest.py` |
| **sink** | writes the daily note + one atomic note per signal (with `reason`, `Community take`, fillable `rating:`); `ntfy` push. `dry_run` → `_scratch/`, ntfy muted | `sink/vault.py`, `sink/notify.py` |
| **feedback** | recomputes a preference profile from your rated notes each run; nudges pre-rank + triage. Rated notes are never overwritten | `process/feedback.py` |

## Sources

| Source | What we pull | Notes |
|--------|--------------|-------|
| **Hacker News** | `front_page` (top stories), up to `limit` (60), via the Algolia API. Captures title, URL, points, comment count. | One request per list — no per-item fetches. We don't filter at fetch; triage scores relevance. |
| **Show HN** | Algolia `show_hn` — maker launches & demos as their own lane (`source: show_hn`, tagged `showcase`) | Split out of the HN bucket so launches are a distinct channel. Threads get the HN "community take". |
| **Launch HN** | YC company launches via Algolia `query="Launch HN"`; batch auto-tagged (`yc/W25`, `yc/P26`…) | The cleanest free "YC-backed ideas space" — structured, dated, AI/agent-heavy. |
| **YC RFS** | scrape of `ycombinator.com/rfs` — the ideas YC actively wants funded (e.g. *Software for Agents*, *AI-Native Discovery Engines*) | Low-frequency (changes rarely); the watermark dedups it after day one. |
| **Reddit** | newest posts from 6 subs (`ClaudeAI`, `ChatGPTCoding`, `LocalLLaMA`, `AI_Agents`, `vibecoding`, `cursor`) | Uses each sub's RSS feed (Reddit 403s the unauth `.json` API). Requests spaced 2s + Retry-After (RSS rate-limits). |
| **GitHub Trending** | repos making the biggest star moves — scrape of `github.com/trending` for **daily + weekly** windows, deduped. Captures `owner/repo`, description, and star count ("N stars today/this week"). | This is the "GitHunt" — discovery of star-gainers. Optional language filter (`languages: []` = all). |
| **OSSInsight** | repos that *gained* the most stars in the window (≥ `min_stars`) via `api.ossinsight.io` | True star-velocity (vs. trending's snapshot). Period configurable (`past_week`, …). |
| **RSS** | 10 curated industry feeds: Simon Willison, Latent Space, Interconnects, Claude Code + Codex release feeds, GitHub blog + changelog, OpenAI news, Product Hunt | `feedparser`, `limit` entries each. |
| **Seed URLs** | pinned one-off links Stevie explicitly wants Cerebro to ingest, starting with Simon Willison's `shot-scraper video` article | Use when a specific blog/repo/post matters even if its parent feed is already watched; dedup watermark keeps it from repeating forever. |
| **Gmail** | newsletter mail matching `(label:newsletters OR from:<senders>) newer_than:1d` (TLDR, Ben's Bites, ByteByteGo, …) | Via `gws`; each newsletter is treated as a link-aggregator. Intermittent (0 when no new mail in the window). |
| **X / Twitter** | tweets from your `search_terms` (filtered by `min_likes`) + all tweets from curator/follow accounts; **curator listicles auto-explode into one signal per embedded repo** | `twscrape` with your saved Firefox cookies — free, headless, no API key. Engagement (likes/RTs/replies/views) stored in note frontmatter. Skips gracefully if logged out. |

## Watermark

There is **no per-source timestamp cursor**. CEREBRO re-fetches each run (sources are
recency-bounded) and suppresses repeats with **content-hash dedup over a rolling 14-day
window** in the SQLite `seen` table — that table *is* the high-water mark.

```
per signal:
  canonical URL  = strip utm_/tracking params, lowercase host, drop fragment + trailing slash
  url_hash       = sha256(canonical)[:16]
  simhash        = 63-bit hash over (title + text)

drop if:
  ├─ url_hash already seen this run
  ├─ url_hash in `seen` within the last  dedup_days  (default 14)        ◀── the watermark
  └─ simhash Hamming-distance ≤ 3  vs any signal seen inside the window  (near-dup across sources)

after the run:
  mark EVERY surviving candidate into `seen` (first_seen, last_seen)
  → tomorrow's run won't re-triage them for 14 days
```

Tune `dedup_days` in `config/settings.yaml`; the Hamming threshold in `process/dedup.py`.
Trade-off: an item that scored < 0.5 today won't get a second look for 14 days.

## Feedback

CEREBRO learns from you with **zero extra UI** — you just set a number in Obsidian.
Every atomic note ships with an empty `rating:` field in its frontmatter; put a **1–5**
there on notes you loved or hated. Each run, `process/feedback.py` scans your rated
`Signals/` notes and recomputes a preference profile:

```
rating ≥ 4  ─▶ liked terms   (title + tags)  ─┐
rating ≤ 2  ─▶ disliked terms                 ├─▶ pre-rank boost  (+2 liked, −2 disliked)
per-source / per-category mean rating         ─┴─▶ triage prompt  (source-trust + topic hints)
```

So a source you consistently rate 5 floats up and a topic you keep rating 1 sinks — no
config edits. **Rated notes are never overwritten**, so your scores survive re-runs.

## Source health

Every run logs each source's item count and ok/fail into the SQLite `source_health` table.
`cerebro --health` prints runs / avg-yield / zero-or-fail count / last-seen per source, so a
source that silently dies (expired X cookie, GitHub layout change) shows up as a string of
zeros instead of vanishing unnoticed.

## Configuration

Three files under `config/` (`settings.yaml` is gitignored — copy from `settings.example.yaml`):

| File | Holds |
|------|-------|
| `settings.yaml` | vault path, `dry_run`, `depth` (min/max/score_threshold), `dedup_days`, `models` (triage/digest aliases), `ntfy.topic`, schedule. **Gitignored** (ntfy topic is sensitive). |
| `sources.yaml` | per-source toggles + tuning (subreddits, RSS feeds, X search-terms/accounts, HN lists, GitHub windows) |
| `interest-matrix.yaml` | the triage rubric — 4 categories with descriptions + tags the LLM scores against |

### Adding / changing sources

**Tune an existing source — config only, no code:**

```yaml
# config/sources.yaml
rss:    { feeds: [ ...add a feed URL... ] }
reddit: { subreddits: [ ...add a sub... ] }
x:      { search_terms: [...], accounts: [ ...add a handle... ] }
```

**Add a brand-new source type — 3 steps:**

1. Write `cerebro/sources/<name>.py` exposing:
   ```python
   def fetch(cfg: dict, settings) -> list[Signal]: ...
   ```
   Return `Signal(url, title, source="<name>", clean_text=..., captured=now_iso(), meta={...})`.
   Catch your own errors and return `[]` to skip gracefully.
2. Register it in `cerebro/sources/__init__.py`:
   ```python
   from . import <name>
   SOURCES = { ..., "<name>": <name>.fetch }
   ```
3. Add a config block under `config/sources.yaml` with `enabled: true`.

The orchestrator picks it up automatically — same funnel, same dedup, same triage.

## Run it

```bash
# one-time
python3 -m venv .venv && .venv/bin/pip install -e .
cp config/settings.example.yaml config/settings.yaml   # set vault path + ntfy topic
pre-commit install                                     # local secret scanners

# dry-run (writes to <vault>/_scratch/, ntfy muted)
.venv/bin/python -m cerebro --dry-run

# per-source yield/failure history (spot a silently-dead source)
.venv/bin/python -m cerebro --health

# go live (your call, after reviewing the _scratch/ briefing):
#   1. set dry_run: false in config/settings.yaml
#   2. load the daily 07:00 job
cp scripts/com.cerebro.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cerebro.daily.plist
```

Source prerequisites (all self-auth, no keys stored by CEREBRO): **Claude Code** logged in ·
**X** logged into x.com in Firefox (twscrape reads the cookie) · **Gmail** `gws auth login --readonly -s gmail`.

## Output

```
<vault>/
├── Daily/2026-06-20.md      # the briefing — themed, wikilinked, frontmatter incl. token usage
└── Signals/<url_hash>.md     # one atomic note per signal (Dataview-queryable)
```

Atomic-note frontmatter: `title`, `category`, `tags`, `source`, `url`, `score`, `reason`
(why triage kept it), `captured`, and a fillable `rating:` (see [Feedback](#feedback)).
Filenames are the URL hash → idempotent re-runs.

## Cost

LLM runs via Claude Code (subscription, not metered API). A full run ≈ **575k tokens / ~10
`claude` calls / ~$1.15 API-equivalent** — ~60% of that is Claude Code's own ~35k cached
context × the call count, not your signal text. Bump the triage batch (60 → 120) to halve
the call count if you want it leaner. Sources are free APIs / cookies.

## Security

Public repo, **secrets-out by design**: no API keys (Claude Code, X cookies, and `gws` all
self-authenticate outside the repo). The only sensitive values — the `ntfy` topic and the X
`accounts.db` (cookies) — are gitignored. Two scanners (gitleaks + GitGuardian) run in
pre-commit and CI on every push. See [`SECURITY.md`](./SECURITY.md).

## Status

All 8 phases complete and validated end-to-end (dry-run produces a real 25-signal briefing).
Design: [`SPEC.md`](./SPEC.md) · build plan: [`plans/cerebro-implementation.md`](./plans/cerebro-implementation.md).
