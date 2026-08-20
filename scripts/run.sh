#!/usr/bin/env bash
# launchd entrypoint. Claude Code, gws, and twscrape self-authenticate — no secrets here.
# launchd hands us a bare PATH (/usr/bin:/bin:...), so it can't see `claude` (~/.local/bin)
# or `gws`/`node` (nvm). Put them back before the run, else every LLM call 'command not found'.
set -euo pipefail
cd "$(dirname "$0")/.."
NODE_BIN="$(dirname "$(ls -t "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | head -1)")"
export PATH="$HOME/.local/bin:${NODE_BIN:-$HOME/.nvm/versions/node/current/bin}:$PATH"

.venv/bin/python -m cerebro

# The vault is a separate Git repository. Keep generated briefings visible in
# its remote, not only on this Mac.
VAULT_PATH="$(.venv/bin/python -c 'from cerebro.config import load; print(load().vault_path)')"
git -C "$VAULT_PATH" add -- Daily Signals
if ! git -C "$VAULT_PATH" diff --cached --quiet; then
  git -C "$VAULT_PATH" commit -S -m "vault: $(date +%F) daily briefing"
  git -C "$VAULT_PATH" push
fi
