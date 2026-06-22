#!/usr/bin/env bash
# launchd entrypoint. Claude Code, gws, and twscrape self-authenticate — no secrets here.
# launchd hands us a bare PATH (/usr/bin:/bin:...), so it can't see `claude` (~/.local/bin)
# or `gws`/`node` (nvm). Put them back before the run, else every LLM call 'command not found'.
set -euo pipefail
cd "$(dirname "$0")/.."
NODE_BIN="$(dirname "$(ls -t "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | head -1)")"
export PATH="$HOME/.local/bin:${NODE_BIN:-$HOME/.nvm/versions/node/current/bin}:$PATH"
exec .venv/bin/python -m cerebro
