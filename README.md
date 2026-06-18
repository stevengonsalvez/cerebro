# CEREBRO 🧠📡

> Scans the noise for the signals matching your profile.
> A local-first, token-minimal daily tech-intelligence pipeline.
> Operator: **Steverebro** at the console.

CEREBRO ingests raw tech signals (Gmail newsletters, Hacker News, Reddit, GitHub
Trending, RSS, X), filters them against a hyper-specific interest matrix, and writes
a clean "explain-to-me" briefing plus atomic, Dataview-queryable notes into an
Obsidian vault — daily, at 07:00, via `launchd`. Filtering is done cheaply by Haiku
4.5; the user-facing digest by Sonnet 4.6. Target spend ~$4–5/month.

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

- **All secrets via Bitwarden Secrets Manager (`bws`).** The pipeline fetches
  `ANTHROPIC_API_KEY` (and any optional keys) at runtime from a `bws` machine
  account. Nothing secret is ever written to the repo.
- **Bootstrap token in Keychain.** `BWS_ACCESS_TOKEN` lives in the macOS Keychain
  (service `cerebro-bws`) and is exported by `scripts/run.sh` — never in the plist,
  never in the repo.
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

# 2. Bitwarden Secrets Manager CLI + bootstrap token
brew install bitwarden/tap/bws        # or per Bitwarden docs
security add-generic-password -s cerebro-bws -a "$USER" -w '<BWS_ACCESS_TOKEN>'

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
