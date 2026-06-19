#!/usr/bin/env bash
# launchd entrypoint. Claude Code, bird, and gws self-authenticate — no secrets here.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m cerebro
