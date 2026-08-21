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

.venv/bin/python -m cerebro

# Weekly roundup for the last COMPLETE ISO week: deterministic, no LLM, write-once.
# No flag: dry_run comes from settings.yaml, exactly like the daily run above. On the live
# install that is `dry_run: false`, so this writes Weekly/ for real; on a dev checkout with
# only settings.example.yaml it writes _scratch/Weekly/. Never hardcode --write here.
# Soft-fail (the `|| echo` also keeps it out of the ERR trap, which is intended) — the
# daily briefing must still reach the vault if the roundup breaks.
.venv/bin/python -m cerebro roundup || echo "[warn] weekly roundup failed" >&2

# The vault is a separate Git repository. Keep generated briefings visible in
# its remote, not only on this Mac.
VAULT_PATH="$(.venv/bin/python -c 'from cerebro.config import load; print(load().vault_path)')"
# `git add` exits 128 on a pathspec matching nothing, and `set -e` would then kill the push.
# Weekly/ legitimately may not exist (first ever run, or a roundup that soft-failed).
mkdir -p "$VAULT_PATH/Weekly"
git -C "$VAULT_PATH" add -- Daily Signals Weekly
if ! git -C "$VAULT_PATH" diff --cached --quiet; then
  git -C "$VAULT_PATH" commit -S -m "vault: $(date +%F) daily briefing"
  git -C "$VAULT_PATH" push
fi
