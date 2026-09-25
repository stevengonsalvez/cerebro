#!/usr/bin/env bash
# Dead-man check for the daily run. Pages the phone if today's briefing has not
# reached the vault's remote, or has not been published on the site, by the time this fires.
#
# DELIBERATELY DEPENDS ON NOTHING THE RUN DEPENDS ON. No Python, no .venv, no Orca,
# no `claude`. The daily run died for 17 days (2026-09-07..09-23) because .venv was
# deleted, and its own failure page ran through the same missing .venv/bin/python, so
# nothing ever paged. A check that shares a dependency with the thing it checks goes
# down with it. This uses bash, sed, git and /usr/bin/curl, all of which ship with macOS.
#
# It also catches the failure the run cannot report at all: the scheduler never
# starting it. The run is an Orca automation, and the local Orca is the desktop app, so
# if Orca was closed at 07:00 there is no run and nothing inside the run to notice.
#
# Checks the REMOTE, not just the working tree: a briefing written but never pushed
# leaves the site stale exactly as a missing one does.
set -u
cd "$(dirname "$0")/.."

today="$(date +%F)"
topic="$(sed -n 's/^ *topic: *"\(.*\)"/\1/p' config/settings.yaml 2>/dev/null)"

page() {
  if [ -z "$topic" ]; then
    echo "deadman: $1 (and no ntfy topic in config/settings.yaml to page)" >&2
    exit 2
  fi
  /usr/bin/curl -fsS -m 20 -H "Priority: high" -H "Tags: warning" \
    -d "cerebro: $1." \
    "https://ntfy.sh/$topic" >/dev/null 2>&1
  echo "deadman: paged: $1" >&2
  exit 1
}

[ -f "vault/Daily/$today.md" ] || page "no briefing for $today by $(date +%H:%M). Check the Orca automation 'cerebro daily'"

git -C vault fetch -q origin 2>/dev/null || page "briefing for $today exists but the vault remote is unreachable"
git -C vault log origin/main -n 20 --format=%s | grep -q "^vault: $today daily briefing$" \
  || page "briefing for $today was written but never pushed"

# AND ON THE SITE. The vault being right is not the finish line: on 2026-09-25 the run
# pushed a correct briefing, the deploy hook returned 200, and the site build then failed
# on its own copy gate, so the page never went live. This check said "ok" that morning
# because it stopped at the vault. A reader only sees the site, so that is what counts.
site="${CEREBRO_SITE_URL:-https://stevengonsalvez.com}"
code="$(/usr/bin/curl -s -o /dev/null -m 20 -w '%{http_code}' "$site/cerebro/$today")"
[ "$code" = "200" ] || page "briefing for $today is in the vault but not on the site (HTTP $code). Check the latest Vercel deploy of stevengonsalvez.github.io"

echo "deadman: ok, $today is on the remote and live on the site"
