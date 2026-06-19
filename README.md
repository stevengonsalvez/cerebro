# CEREBRO 🧠📡

> Scans the noise for the signals matching your profile.
> A local-first, token-minimal daily tech-intelligence pipeline.
> Operator: **Steverebro** at the console.

CEREBRO ingests raw tech signals (Gmail newsletters, Hacker News, Reddit, GitHub
Trending, RSS, X), filters them against a hyper-specific interest matrix, and writes
a clean "explain-to-me" briefing plus atomic, Dataview-queryable notes into an
Obsidian vault — daily, at 07:00, via `launchd`. Filtering is done cheaply by Haiku
4.5; the user-facing digest by Sonnet 4.6 — both run via Claude Code on the
machine (no API key; covered by your Claude Code subscription).

## Flow

```
SOURCES (free)         PRE-FILTER (cheap)         LLM (paid, tiny)     SINK
 Gmail HN Reddit  ─▶  dedup ▶ regex junk-gate ▶  Haiku 4.5 triage ▶  Sonnet 4.6
 GitHub RSS X         (simhash)   (~$0)          (JSON score/tag)    digest
                          ▲ kills ~80%                                  │
                    interest-matrix rubric                             ▼
                                                              Obsidian vault
   sched: launchd 07:00 · state: SQLite (14-day dedup) · notify: ntfy
```

Full design: [`SPEC.md`](./SPEC.md) · build plan: [`plans/cerebro-implementation.md`](./plans/cerebro-implementation.md).

## 🔒 Security posture

This repo is **public** and contains **zero secrets** by design.

- **No API keys.** The LLM runs via Claude Code on the machine (`claude -p`),
  which uses its own login. `bird` (X) reads the browser cookie; `gws` (Gmail)
  uses its own Google OAuth. Nothing secret is written to the repo.
- **`ntfy` topic + vault path live only in `config/settings.yaml`** (gitignored).
  Committed `*.example` files are placeholders.
- **Two secret scanners, both pre-commit and CI:**
  - [gitleaks](https://github.com/gitleaks/gitleaks) — `.gitleaks.toml`
  - [GitGuardian ggshield](https://github.com/GitGuardian/ggshield) — `.gitguardian.yaml`
  - CI: [`.github/workflows/security.yml`](./.github/workflows/security.yml)
  - Local: [`.pre-commit-config.yaml`](./.pre-commit-config.yaml)
- See [`SECURITY.md`](./SECURITY.md) for the policy and reporting.

## Setup (one-time)

```bash
# 1. local secret scanners (defense in depth)
brew install gitleaks                 # already? skip
pipx install ggshield                 # or: pip install ggshield
pre-commit install                    # activate local hooks
pre-commit autoupdate                 # pin scanner hooks to latest

# 2. self-authenticating tools (CEREBRO stores no keys)
#    - Claude Code: already logged in (`claude` on PATH)
#    - bird: log into x.com in Firefox/Chrome  → `bird whoami` to confirm
#    - gws:  Google OAuth                       → `gws gmail users getProfile`

# 3. config (gitignored)
cp config/settings.example.yaml config/settings.yaml   # fill real values
```

GitHub-side secrets (you add — never committed):

```bash
gh secret set GITGUARDIAN_API_KEY     # enables the ggshield CI job
```

## Status

Design + plan complete. Implementation tracked in `plans/cerebro-implementation.md`
(8 phases / 5 waves). Phase 1 = scaffold/config/state/secrets.
