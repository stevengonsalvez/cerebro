#!/usr/bin/env bash
# CEREBRO bootstrap for a new machine.
# Prereqs: this repo cloned, and `.env` pulled from Bitwarden into the repo root
# (`bw get item cerebro/.env` → its notes, or the attachment). Then run this.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "✗ missing .env — pull it from Bitwarden into the repo root first"; exit 1; }

# 1. python env
python3 -m venv .venv
.venv/bin/pip install -e . >/dev/null
echo "✓ venv + deps"

# 2. settings.yaml — non-secret tunables; ntfy topic + vault path come from .env overrides
[ -f config/settings.yaml ] || cp config/settings.example.yaml config/settings.yaml
echo "✓ config/settings.yaml"

# 3. restore Gmail (gws) OAuth dir if bundled in .env (portable base64 decode via python)
gws_b64=$(grep -E '^GWS_CONFIG_B64=' .env | cut -d= -f2-)
if [ -n "$gws_b64" ]; then
  mkdir -p "$HOME/.config"
  printf '%s' "$gws_b64" | python3 -c 'import sys,base64; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))' \
    | tar -C "$HOME/.config" -xzf -
  echo "✓ restored ~/.config/gws (Gmail)"
else
  echo "· GWS_CONFIG_B64 empty — run: gws auth login --readonly -s gmail"
fi

cat <<'NEXT'

Bootstrap done. Two interactive steps remain (can't be carried in .env):
  1. claude            # log into your Claude Code subscription (no API key by design)
  2. clone the private vault repo to $CEREBRO_VAULT (the path in .env), if not already

Verify:  .venv/bin/python -m cerebro --dry-run
Go live: set dry_run:false in config/settings.yaml, then load scripts/com.cerebro.daily.plist
NEXT
