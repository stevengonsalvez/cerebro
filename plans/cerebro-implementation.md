# CEREBRO Implementation Plan

## Overview
Build a local-first Python pipeline that, daily at 07:00 via launchd, ingests tech signals from
6 sources, runs them through a free pre-filter → Haiku triage → Sonnet digest funnel, and writes a
briefing + atomic notes into a standalone local Obsidian vault. Source of truth: `SPEC.md`.

## Current State Analysis
Greenfield. No existing code. Working dir `/Users/stevengonsalvez/d/git/cerebro/`. Not yet a git
repo. External tools already on the machine: `bird` (X CLI), `gog` (Gmail CLI), `bws` (Bitwarden
Secrets Manager), `ntfy`. Python 3.x assumed present.

## Desired End State
`python -m cerebro` (and the launchd job) runs the full funnel and writes
`Daily/YYYY-MM-DD.md` + `Signals/<hash>.md` into the vault, ntfy-pings on completion,
costs ~$4–5/mo. Verify: a real run produces a daily note with 15–25 linked, scored, tagged signals
and no duplicates within 14 days.

### Key Decisions (from SPEC.md — do not re-litigate)
- Python · launchd 07:00 · bird burner-X read-only · Haiku filter + Sonnet digest
- Vault `~/d/git/cerebro-vault` (standalone local Obsidian vault) · bws secrets · ntfy · 14-day dedup
- Rollout: dry-run to `_scratch/` first, then live

## What We're NOT Doing
- No TTS/audio digest, no GitHub Actions cloud fallback, no web UI, no Ollama, no Batches API (v1).
- No posting to X (read-only). No prompt-cache engineering (moot at this volume).

## Implementation Approach
Layered modules behind a thin orchestrator. Sources normalize everything to a single `Signal`
dataclass; every downstream stage consumes/produces `list[Signal]`. Config in YAML, secrets via bws,
state in SQLite. Dry-run is a single settings flag that reroutes the sink and mutes ntfy.

## Project File Tree
```
cerebro/
├── SPEC.md
├── README.md
├── pyproject.toml              # deps: anthropic, feedparser, trafilatura, pyyaml, requests, simhash
├── .gitignore                  # .env, *.sqlite, __pycache__, .venv
├── .env.example                # BWS_ACCESS_TOKEN, NTFY_TOPIC (non-secret defaults)
├── config/
│   ├── settings.yaml           # vault_path, run depth, dedup_days, models, dry_run, ntfy topic
│   ├── interest-matrix.yaml    # 4 categories + tags (the triage rubric)
│   └── sources.yaml            # subreddits, newsletter senders, RSS feeds, X tags/accounts
├── cerebro/
│   ├── __init__.py
│   ├── __main__.py             # entry: python -m cerebro [--dry-run]
│   ├── config.py               # load + merge yaml/env → Settings
│   ├── secrets.py              # bws fetch wrapper
│   ├── models.py               # Signal dataclass + RunStats
│   ├── state.py                # SQLite seen-hash + run log
│   ├── orchestrator.py         # the funnel
│   ├── sources/
│   │   ├── __init__.py         # SOURCES registry
│   │   ├── base.py             # Source protocol
│   │   ├── hackernews.py
│   │   ├── reddit.py
│   │   ├── github_trending.py
│   │   ├── rss.py
│   │   ├── gmail.py            # subprocess → gog
│   │   └── x_bird.py           # subprocess → bird
│   ├── process/
│   │   ├── extract.py          # trafilatura HTML→text
│   │   ├── dedup.py            # url-canonical + simhash
│   │   └── junkgate.py         # lenient regex
│   ├── llm/
│   │   ├── client.py           # anthropic client factory
│   │   ├── triage.py           # Haiku batch, strict JSON
│   │   └── digest.py           # Sonnet briefing
│   ├── sink/
│   │   ├── vault.py            # daily + atomic notes
│   │   └── notify.py           # ntfy
│   └── prompts/
│       ├── triage.md
│       └── digest.md
├── scripts/
│   ├── run.sh                  # wrapper: export BWS token, exec python -m cerebro
│   └── com.cerebro.daily.plist # launchd
├── plans/cerebro-implementation.md
└── tests/
    ├── fixtures/               # sample HN/Reddit/RSS payloads, sample newsletter HTML
    └── test_*.py
```

## Module Contracts

### `models.Signal`
```python
@dataclass
class Signal:
    url: str
    title: str
    source: str                 # hackernews|reddit|github|rss|gmail|x
    canonical_url: str = ""     # set in dedup
    url_hash: str = ""          # sha256(canonical_url)[:16], set in dedup
    raw_html: str = ""          # if fetched
    clean_text: str = ""        # set by extract
    simhash: int = 0            # set by dedup
    score: float = 0.0          # set by triage (0..1)
    category: str = ""          # set by triage
    tags: list[str] = field(default_factory=list)   # set by triage
    captured: str = ""          # ISO8601, set at fetch
    meta: dict = field(default_factory=dict)        # points/author/stars/sender
```

### `sources.base.Source`
```python
class Source(Protocol):
    name: str
    def fetch(self, cfg: dict, settings: Settings) -> list[Signal]: ...
# Each module exposes `source: Source`. Registry in sources/__init__.py: SOURCES = {name: source}.
# Per-source failure is caught by the orchestrator → logged, run continues.
```

### `secrets.get`
```python
def get(name: str) -> str:
    # `bws secret get <id>` keyed by config; BWS_ACCESS_TOKEN must be in env.
    # Caches within a run. Raises CerebroSecretError on miss.
```

### `process` stage signatures
```python
extract.enrich(signals: list[Signal]) -> list[Signal]   # fills clean_text via trafilatura
dedup.dedupe(signals, state) -> list[Signal]            # canonical+hash+simhash; drops in-run + 14-day dups
junkgate.filter(signals) -> list[Signal]                # lenient: drops non-EN/spam/empty only
```

### `llm.triage.triage`
```python
def triage(signals: list[Signal], matrix: dict, settings) -> list[Signal]:
    # Batches title+200-char snippet+source. Model claude-haiku-4-5.
    # output_config json_schema → {"results":[{"id","relevant":bool,"score":0..1,"category","tags":[]}]}
    # Mutates score/category/tags; returns signals where relevant and score >= threshold.
```

### `llm.digest.digest`
```python
def digest(top: list[Signal], settings) -> DigestResult:
    # Model claude-sonnet-4-6. Input = top 15-25 by score, clean_text trimmed.
    # Returns: briefing_markdown (the daily note body) + {url_hash: one_liner} per signal.
```

### `sink.vault.write` / `sink.notify.push`
```python
vault.write(date, briefing, signals, settings) -> Paths   # _scratch/ if dry_run else Cerebro/
notify.push(stats, daily_path, settings) -> None          # ntfy; no-op if dry_run
```

## SQLite Schema (`state.py`)
```sql
CREATE TABLE IF NOT EXISTS seen (
  url_hash    TEXT PRIMARY KEY,
  simhash     INTEGER,
  url         TEXT,
  title       TEXT,
  source      TEXT,
  category    TEXT,
  score       REAL,
  first_seen  TEXT NOT NULL,        -- ISO date
  last_seen   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_first ON seen(first_seen);

CREATE TABLE IF NOT EXISTS runs (
  run_id      TEXT PRIMARY KEY,     -- ISO timestamp
  started_at  TEXT, finished_at TEXT,
  raw_count   INTEGER, after_dedup INTEGER, after_triage INTEGER, digested INTEGER,
  dry_run     INTEGER, x_ok INTEGER, error TEXT
);
```
Dedup rule: drop if `url_hash` seen within `dedup_days`, OR simhash Hamming-distance ≤ 3 vs any
row in window. On keep, upsert `seen` (update `last_seen`).

---

## Phase 1: Scaffold, Config, State, Secrets
<!-- wave: 1 | depends_on: [] | files: [pyproject.toml, .gitignore, .env.example, config/settings.yaml, config/interest-matrix.yaml, config/sources.yaml, cerebro/__init__.py, cerebro/config.py, cerebro/secrets.py, cerebro/models.py, cerebro/state.py] -->

### Changes
- `pyproject.toml`: deps `anthropic, feedparser, trafilatura, pyyaml, requests` (+ a simhash impl, e.g. `simhash` or inline 64-bit).
- `config/settings.yaml`: vault path, `depth: {min: 15, max: 25, score_threshold: 0.5}`, `dedup_days: 14`, models (`triage: claude-haiku-4-5`, `digest: claude-sonnet-4-6`), `dry_run: true` (default ON for safety), `ntfy: {topic: ...}`, `bws: {anthropic_key_id: ...}`.
- `config/interest-matrix.yaml`: the 4 categories + tag lists from SPEC.
- `config/sources.yaml`: subreddits (r/ClaudeAI, r/ChatGPTCoding, r/LocalLLaMA, r/AI_Agents, r/vibecoding, r/cursor), newsletter senders (AI Breakfast, The Rundown, TLDR, Ben's Bites, ByteByteGo), RSS feeds (seed `[]` — fill later), X tags+accounts.
- `config.py`: load+validate → `Settings`. CLI `--dry-run` overrides yaml.
- `secrets.py`, `models.py`, `state.py` per contracts above.

### Success Criteria
**Automated:** `python -c "from cerebro.config import load; load()"` succeeds · `python -c "from cerebro.state import State; State(':memory:').init()"` creates tables · `python -m cerebro --help` works.
**Manual:** `bws secret get <id>` returns the Anthropic key when `BWS_ACCESS_TOKEN` set.

---

## Phase 2: JSON Source Ingestors
<!-- wave: 2 | depends_on: [1] | files: [cerebro/sources/__init__.py, cerebro/sources/base.py, cerebro/sources/hackernews.py, cerebro/sources/reddit.py, cerebro/sources/github_trending.py, cerebro/sources/rss.py] -->

### Changes
- `base.py` Source protocol + registry.
- `hackernews.py`: HN Firebase API — top + show story IDs → items → `Signal`. `meta.points`.
- `reddit.py`: `https://www.reddit.com/r/<sub>/new.json?limit=N` (custom UA), per sub from config.
- `github_trending.py`: trending repos (HTML scrape or known JSON mirror) → `Signal`, `meta.stars`.
- `rss.py`: feedparser per feed, persist ETag/Last-Modified in a small `feeds` table or sidecar to skip unchanged.

### Success Criteria
**Automated:** each module's `fetch()` returns ≥1 `Signal` against a fixture or live call; unit tests parse `tests/fixtures/*`.
**Manual:** spot-check titles/URLs look right for each source.

---

## Phase 3: Gmail + X Ingestors
<!-- wave: 2 | depends_on: [1] | files: [cerebro/sources/gmail.py, cerebro/sources/x_bird.py] -->
Parallel with Phase 2 (disjoint files).

### Changes
- `gmail.py`: subprocess `gog` to query `(label:newsletters OR from:{senders}) newer_than:1d`; parse to `Signal` (newsletter = link-aggregator → also extract embedded links as candidate signals). **Verify exact `gog` subcommand/flags at build (`gog --help`).**
- `x_bird.py`: `bird whoami` first → if non-zero/auth error set `x_ok=False`, ntfy + skip (handled in orchestrator). Else `bird search "<tag>" -n N` per config tag + `bird read/thread` for key accounts → `Signal`. **Verify bird JSON output flag (`bird --help`); fall back to text parse.** Read-only — never `bird tweet/reply`.

### Success Criteria
**Automated:** `gmail.fetch()` returns signals against a labeled inbox; `x_bird.fetch()` returns signals when `bird whoami` is authed.
**Manual:** confirm burner X account is the one `bird whoami` reports; confirm newsletter senders resolve.

---

## Phase 4: Extract · Dedup · Junk-gate
<!-- wave: 3 | depends_on: [1] | files: [cerebro/process/extract.py, cerebro/process/dedup.py, cerebro/process/junkgate.py] -->

### Changes
- `extract.py`: trafilatura on raw_html / fetched URL → `clean_text` (skip if source already gives text, e.g. tweets).
- `dedup.py`: canonicalize URL (strip utm_*, fragments, trailing slash), `url_hash`, 64-bit simhash of title+clean_text; drop in-run dups + 14-day window dups via `state`.
- `junkgate.py`: lenient — drop only non-English (langdetect/heuristic), empty, or obvious spam domains. Everything else passes to triage.

### Success Criteria
**Automated:** dedup collapses a duplicated fixture story to 1; junkgate drops a known-junk fixture, keeps a borderline one; extract returns non-empty text for a sample article.
**Manual:** simhash threshold (≤3) doesn't over-merge distinct stories on a real day's data.

---

## Phase 5: Triage (Haiku) · Digest (Sonnet)
<!-- wave: 3 | depends_on: [1] | files: [cerebro/llm/client.py, cerebro/llm/triage.py, cerebro/llm/digest.py, cerebro/prompts/triage.md, cerebro/prompts/digest.md] -->
Parallel with Phase 4 (disjoint files).

### Changes
- `client.py`: `anthropic.Anthropic()` using key from `secrets.get`.
- `triage.py`: batch survivors; `output_config={"format":{"type":"json_schema","schema":...}}`; `claude-haiku-4-5`; parse → set score/category/tags; keep `score >= threshold`. Retry once on parse fail.
- `digest.py`: `claude-sonnet-4-6`; top 15–25 by score; return briefing markdown + per-signal one-liners. `max_tokens` generous; stream if large.
- `prompts/*.md`: triage rubric embeds the interest-matrix; digest prompt = concise extractive "explain-to-me", grouped by category, no fluff.

### Success Criteria
**Automated:** triage returns valid JSON for a 10-item fixture batch and assigns plausible categories; digest returns non-empty markdown for 15 fixtures.
**Manual:** read a sample digest — tone is skim-friendly, categories correct, no hallucinated links.

---

## Phase 6: Sink — Vault Writer + Notifier
<!-- wave: 3 | depends_on: [1] | files: [cerebro/sink/vault.py, cerebro/sink/notify.py] -->
Parallel with Phases 4–5 (disjoint files).

### Changes
- `vault.py`: write `Daily/<date>.md` (briefing body + `[[wikilinks]]` to signals) and `Signals/<url_hash>.md` (frontmatter: category/tags/source/url/score/captured + one-liner + clean_text excerpt). Target `_scratch/` when `dry_run`. Idempotent by filename.
- `notify.py`: ntfy publish "briefing ready · N signals · <obsidian/file link>"; no-op when `dry_run`.

### Success Criteria
**Automated:** writing 3 fixtures produces 1 daily + 3 signal files with valid YAML frontmatter; dry-run targets `_scratch/`.
**Manual:** open the daily note in Obsidian — wikilinks resolve, Dataview can query `score`/`tags`.

---

## Phase 7: Orchestrator + Wrapper + launchd + Dry-run Gate
<!-- wave: 4 | depends_on: [2,3,4,5,6] | files: [cerebro/__main__.py, cerebro/orchestrator.py, scripts/run.sh, scripts/com.cerebro.daily.plist] -->

### Changes
- `orchestrator.py`: wire the funnel —
  ```
  fetch(all sources; per-source try/except; bird whoami gate → ntfy+skip on X fail)
   → extract → junkgate → dedup(state) → triage(Haiku) → rank/top-N
   → digest(Sonnet) → vault.write → notify.push → state.log_run
  ```
- `__main__.py`: arg parse (`--dry-run`, `--source <name>` for isolated testing), call orchestrator.
- `scripts/run.sh`: `export BWS_ACCESS_TOKEN=$(security find-generic-password -s cerebro-bws -w)` then `exec /path/.venv/bin/python -m cerebro`. (Keeps the bootstrap token out of the plist.)
- `com.cerebro.daily.plist`: `StartCalendarInterval` hour 7 minute 0 (launchd runs a missed calendar job once on wake), `ProgramArguments → run.sh`, `StandardOut/ErrorPath` to a log, `RunAtLoad false`.

### launchd plist
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cerebro.daily</string>
  <key>ProgramArguments</key>
  <array><string>/Users/stevengonsalvez/d/git/cerebro/scripts/run.sh</string></array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>/Users/stevengonsalvez/d/git/cerebro/cerebro.log</string>
  <key>StandardErrorPath</key><string>/Users/stevengonsalvez/d/git/cerebro/cerebro.err.log</string>
  <key>RunAtLoad</key><false/>
</dict></plist>
```

### Success Criteria
**Automated:** `python -m cerebro --dry-run` runs end-to-end, writes to `_scratch/`, logs a `runs` row, sends no ntfy · `plutil -lint com.cerebro.daily.plist` passes.
**Manual:** `launchctl load` the plist; `launchctl start com.cerebro.daily` triggers a dry-run write.

---

## Phase 8: Dry-run Validation → Go Live
<!-- wave: 5 | depends_on: [7] | files: [config/settings.yaml] -->

### Changes
- Run dry-run 1–2 days; eyeball `_scratch/` output (relevance, dedup, digest quality, costs in logs).
- Tune `score_threshold`, simhash distance, subreddit/sender/RSS/X lists, prompts.
- Flip `dry_run: false`; confirm real vault write + ntfy; load launchd for 07:00.

### `[CHECKPOINT:human-verify]`
- **Built:** full pipeline, output in `_scratch/`.
- **Verify:** (1) `Cerebro/_scratch/Daily/<today>.md` reads well, 15–25 signals, correct categories; (2) no dupes; (3) `cerebro.log` shows token spend ~target; (4) X gate behaved.
- **Resume:** "approved" → flip `dry_run: false`, load launchd. Or list fixes.

---

## Testing Strategy
- **Unit:** each source parses its fixture; dedup collapses dups; junkgate keeps/drops correctly; triage parses JSON; vault writes valid frontmatter.
- **Integration:** `python -m cerebro --dry-run` full funnel on live sources → `_scratch/`.
- **Manual:** Obsidian render + Dataview query; launchd trigger; bird/gog auth paths; X-fail ntfy.

## Build Order (waves)
```
Wave 1: Phase 1 (scaffold/config/state/secrets)
Wave 2: Phase 2 (JSON sources)  ||  Phase 3 (gmail+bird)
Wave 3: Phase 4 (process)  ||  Phase 5 (llm)  ||  Phase 6 (sink)
Wave 4: Phase 7 (orchestrator + launchd)
Wave 5: Phase 8 (dry-run → live)  [checkpoint]
```

## References
- Spec: `SPEC.md`
- Vault: `~/d/git/cerebro-vault` (standalone local Obsidian vault)
- External CLIs verified at build: `bird --help`, `gog --help`, `bws --help`, `ntfy`
- Pre-build opens (seed values): RSS feed URLs · X key accounts · Bitwarden secret id for the Anthropic key
```
