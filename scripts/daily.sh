#!/usr/bin/env bash
# The daily run, driven by an agent that may not outlive it.
#
#   scripts/daily.sh start   launch scripts/run.sh in a detached tmux session
#   scripts/daily.sh wait    block up to ~9 minutes; print the EXIT= line or RUNNING
#
# WHY THIS EXISTS. The run is an Orca automation: Orca starts a Claude session with a
# prompt, and the first attempt (2026-09-23) had the agent start run.sh as one of its
# own background tasks and then go idle. The session ended within seconds of that and
# took the pipeline with it, mid-triage, because a background task is a child of the
# agent's process. A tmux session is not, so the pipeline now finishes whatever happens
# to the session that started it.
#
# `wait` is bounded to fit inside a single agent tool call (the Bash tool caps at 10
# minutes), so the agent keeps calling it in the FOREGROUND and never goes idle while
# the run is in flight.
#
# The log lives in logs/ (gitignored). stdout and stderr both go there, and the last
# line is always EXIT=<code>, which is what `wait` looks for.
set -u
cd "$(dirname "$0")/.."

day="$(date +%F)"
name="cerebro-daily-$day"
log="logs/daily-$day.log"
mkdir -p logs

case "${1:-}" in
  start)
    # Idempotent, because the automation can fire more than once in a day (the missed-run
    # grace window, a manual trigger): never two pipelines, never a second write.
    if tmux has-session -t "=$name" 2>/dev/null; then
      echo "already running: $name"; exit 0
    fi
    if grep -qx 'EXIT=0' "$log" 2>/dev/null; then
      echo "already succeeded today: $log"; exit 0
    fi
    tmux new-session -d -s "$name" "scripts/run.sh > '$log' 2>&1; echo EXIT=\$? >> '$log'"
    echo "started: tmux session $name, log $log"
    ;;
  wait)
    for _ in $(seq 1 27); do
      if grep -q '^EXIT=' "$log" 2>/dev/null; then tail -1 "$log"; exit 0; fi
      sleep 20
    done
    echo "RUNNING"
    ;;
  *)
    echo "usage: $0 start|wait" >&2; exit 2
    ;;
esac
