#!/usr/bin/env bash
# launchd entrypoint. Claude Code, gws, and twscrape self-authenticate — no secrets here.
# launchd hands us a bare PATH (/usr/bin:/bin:...), so it can't see `claude` (~/.local/bin)
# or `gws`/`node` (nvm). Put them back before the run, else every LLM call 'command not found'.
set -euo pipefail
cd "$(dirname "$0")/.."
NODE_BIN="$(dirname "$(ls -t "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | head -1)")"
export PATH="$HOME/.local/bin:${NODE_BIN:-$HOME/.nvm/versions/node/current/bin}:$PATH"

# The only ntfy ping fires from orchestrator.py BEFORE the vault push, so everything below
# it used to fail in silence. Anything that dies from here on now pages the phone.
# Plain `set -e` (no `-E`): with errtrace the trap would also fire inside the `$( )`
# command substitutions below, paging twice for one failure.
on_err() {
  local rc=$? line=$1
  .venv/bin/python -c "from cerebro.config import load; from cerebro.sink import notify; \
notify.push_failure('run.sh failed at line $line (rc $rc)', load())" || true
  exit "$rc"
}
trap 'on_err $LINENO' ERR

# Soft failures (the roundup, the deploy hook) must not kill the daily briefing — but
# they must not be SILENT either. `|| echo` alone put one line into an unrotated
# cerebro.err.log that nobody reads, so a permanently broken roundup would stop weekly
# publication with zero alerting. Page the phone here instead, non-fatally: the message
# goes in via argv (never interpolated into the -c source), the whole thing is `|| true`
# so alerting can never become the failure, and being on the RHS of `||` keeps it out of
# the ERR trap, which is what makes it soft.
warn_and_page() {
  echo "[warn] $1" >&2
  .venv/bin/python -c 'import sys
from cerebro.config import load
from cerebro.sink import notify
notify.push_failure(sys.argv[1], load())' "$1" || true
  return 0
}

.venv/bin/python -m cerebro

# Weekly roundup for the last COMPLETE ISO week: deterministic, no LLM, write-once.
# No flag: dry_run comes from settings.yaml, exactly like the daily run above. On the live
# install that is `dry_run: false`, so this writes Weekly/ for real; on a dev checkout with
# only settings.example.yaml it writes _scratch/Weekly/. Never hardcode --write here.
# Soft-fail (the `||` also keeps it out of the ERR trap, which is intended) — the daily
# briefing must still reach the vault if the roundup breaks — but it pages, because a
# roundup that stays broken means the weekly email silently stops going out.
.venv/bin/python -m cerebro roundup || warn_and_page "weekly roundup failed"
# F069 preflight. ADVISORY, never a gate: it pages when the github_events contract has
# moved (exit 3) or the endpoint is unreachable (exit 4), and devs-refresh runs either
# way, because the refresh has its own degradation path and a preflight that blocked the
# run would turn a ClickHouse hiccup into a self-inflicted outage.
.venv/bin/python -m cerebro devs-contract || warn_and_page "gh archive contract check failed"
# F059 preflight. Also advisory: an over-scoped or missing token is a credential problem,
# not a reason to stop publishing what the lane can still read. Exit 5 is over-scoped or
# refused, exit 6 is "no token reached the process" — the failure the morning after a
# rotation that stopped before the env was updated.
.venv/bin/python -m cerebro devs-token-check || warn_and_page "gh token check failed"
.venv/bin/python -m cerebro devs-refresh || warn_and_page "devs refresh failed"

# The vault is a separate Git repository. Keep generated briefings visible in
# its remote, not only on this Mac.
VAULT_PATH="$(.venv/bin/python -c 'from cerebro.config import load; print(load().vault_path)')"
# `git add` exits 128 on a pathspec matching nothing, and `set -e` would then kill the push.
# Weekly/ legitimately may not exist (first ever run, or a roundup that soft-failed).
mkdir -p "$VAULT_PATH/Weekly"
mkdir -p "$VAULT_PATH/Devs"
git -C "$VAULT_PATH" add -- Daily Signals Weekly Devs
if ! git -C "$VAULT_PATH" diff --cached --quiet; then
  git -C "$VAULT_PATH" commit -S -m "vault: $(date +%F) daily briefing"
  git -C "$VAULT_PATH" push
  # Public vault changed → tell the site to rebuild /cerebro. Soft-fail, and swallow curl's
  # own stderr as defence-in-depth. NOT because curl leaks the URL — measured on curl 8.7.1,
  # an HTTP failure prints `curl: (56) The requested URL returned error: 404` (no URL) and a
  # DNS failure prints the host only, never the secret path. The redirect is here because
  # other curl builds and other exit modes (e.g. exit 3 malformed-URL diagnostics) are less
  # disciplined, and cerebro.err.log is an unrotated plaintext file. Do not delete it after
  # "verifying" that today's curl happens not to leak.
  DEPLOY_HOOK="$(.venv/bin/python -c 'import os, cerebro.config; print(os.environ.get("VERCEL_DEPLOY_HOOK_URL", ""))')"
  if [ -n "$DEPLOY_HOOK" ]; then
    curl -fsS -m 20 -X POST -o /dev/null "$DEPLOY_HOOK" 2>/dev/null \
      || warn_and_page "vercel deploy hook POST failed"
  fi
fi
