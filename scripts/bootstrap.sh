#!/usr/bin/env bash
# CEREBRO bootstrap for a new machine.
# Prereqs: cloned with submodules (`git clone --recursive`, or run step 1 below), and
# `.env` pulled from Bitwarden into the repo root (item cerebro/.env). Then run this.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "✗ missing .env — pull it from Bitwarden into the repo root first"; exit 1; }

# 1. private vault submodule (needs access to the private cerebro-vault repo)
git submodule update --init --recursive
( cd vault && command -v pre-commit >/dev/null && pre-commit install >/dev/null 2>&1 || true )
echo "✓ vault submodule ($(ls vault/Signals/*.md 2>/dev/null | wc -l | tr -d ' ') signal notes)"

# 2. python env
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

Bootstrap done. One interactive step remains (can't be carried in .env):
  1. claude            # log into your Claude Code subscription (no API key by design)

The vault is the ./vault private submodule — already populated above.
Verify:  .venv/bin/python -m cerebro --dry-run
Go live: set dry_run:false in config/settings.yaml, then load scripts/com.cerebro.daily.plist
NEXT
