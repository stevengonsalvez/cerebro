from __future__ import annotations

import base64
import json
import subprocess

from ..models import Signal
from .base import now_iso

# ponytail: each newsletter = one Signal (raw_html → extract → triage). Exploding each
# newsletter into its embedded links is a later enhancement, not v1.


def _gws(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gws", *args], capture_output=True, text=True, timeout=60)


def _walk(part: dict, want: str) -> str:
    body = part.get("body", {})
    if part.get("mimeType") == want and body.get("data"):
        return base64.urlsafe_b64decode(body["data"]).decode("utf-8", "replace")
    for p in part.get("parts", []):
        if (r := _walk(p, want)):
            return r
    return ""


def fetch(cfg: dict, settings) -> list[Signal]:
    senders = cfg.get("senders", [])
    ors = [f'label:{cfg.get("label", "newsletters")}'] + [f'from:"{s}"' for s in senders]
    q = f'({" OR ".join(ors)}) newer_than:{cfg.get("newer_than", "1d")}'

    r = _gws(["gmail", "users", "messages", "list",
              "--params", json.dumps({"userId": "me", "q": q, "maxResults": 50})])
    if r.returncode != 0 or '"error"' in r.stdout:
        return []  # unauthed / insufficient scope → skip gracefully

    try:
        msgs = json.loads(r.stdout).get("messages", [])
    except json.JSONDecodeError:
        return []

    out: list[Signal] = []
    for m in msgs:
        g = _gws(["gmail", "users", "messages", "get",
                  "--params", json.dumps({"userId": "me", "id": m["id"], "format": "full"})])
        if g.returncode != 0:
            continue
        try:
            msg = json.loads(g.stdout)
        except json.JSONDecodeError:
            continue
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        html = _walk(payload, "text/html") or _walk(payload, "text/plain")
        out.append(Signal(
            url=f'https://mail.google.com/mail/u/0/#inbox/{m["id"]}',
            title=headers.get("subject", ""), source="gmail", raw_html=html,
            captured=now_iso(), meta={"from": headers.get("from", ""), "gmail_id": m["id"]},
        ))
    return out
