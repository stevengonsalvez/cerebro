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

# The vault is a separate Git repository. Keep generated briefings visible in
# its remote, not only on this Mac.
VAULT_PATH="$(.venv/bin/python -c 'from cerebro.config import load; print(load().vault_path)')"
git -C "$VAULT_PATH" add -- Daily Signals
if ! git -C "$VAULT_PATH" diff --cached --quiet; then
  git -C "$VAULT_PATH" commit -S -m "vault: $(date +%F) daily briefing"
  git -C "$VAULT_PATH" push
fi
