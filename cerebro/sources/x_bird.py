from __future__ import annotations

import json
import subprocess

from ..models import Signal
from .base import now_iso

# ponytail: bird rides X's undocumented GraphQL — `bird search` was 404'ing at build time
# (X rotated query IDs). So this skips on any failure and the field mapping below is
# best-effort; verify the shapes once `bird search --json` is healthy again.


def _bird(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["bird", *args], capture_output=True, text=True, timeout=60)


def authed() -> bool:
    r = _bird(["whoami"])
    return r.returncode == 0 and "Logged in" in (r.stdout + r.stderr)


def _parse(raw: str, ctx: str) -> list[Signal]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    tweets = data if isinstance(data, list) else (data.get("tweets") or data.get("results") or [])
    out: list[Signal] = []
    for t in tweets:
        if not isinstance(t, dict):
            continue
        tid = t.get("id") or t.get("id_str") or t.get("rest_id")
        user = (t.get("user") or {}).get("screen_name") or t.get("username") or t.get("screenName") or ""
        text = t.get("text") or t.get("full_text") or t.get("content") or ""
        url = t.get("url") or (
            f"https://x.com/{user}/status/{tid}" if user and tid
            else f"https://x.com/i/status/{tid}" if tid else "")
        if not url:
            continue
        out.append(Signal(url=url, title=text[:200], source="x", clean_text=text,
                          captured=now_iso(), meta={"author": user, "query": ctx}))
    return out


def fetch(cfg: dict, settings) -> list[Signal]:
    if not authed():
        return []  # no x.com cookie → skip (orchestrator notes X unavailable)
    out: list[Signal] = []
    for term in cfg.get("search_terms", []):
        r = _bird(["search", term, "-n", str(cfg.get("per_query", 10)), "--json"])
        if r.returncode == 0:
            out += _parse(r.stdout, term)
    for acct in cfg.get("accounts", []):
        r = _bird(["search", f"from:{acct}", "-n", str(cfg.get("per_query", 10)), "--json"])
        if r.returncode == 0:
            out += _parse(r.stdout, f"@{acct}")
    return out
