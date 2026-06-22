from __future__ import annotations

import asyncio
import glob
import os
import pathlib
import re
import sqlite3

from ..models import Signal
from .base import now_iso

# Free, headless X reads via twscrape: it computes X's x-client-transaction-id (the thing
# bird/twikit choke on) and uses your saved Firefox cookies. accounts.db holds the auth_token
# → repo-root, gitignored, never committed. Cookies are re-loaded from Firefox each run so
# they stay fresh. ponytail: if X breaks twscrape, fetch() returns [] (graceful skip).

ROOT = pathlib.Path(__file__).resolve().parents[2]
ACCOUNTS_DB = str(ROOT / "accounts.db")
_GH = re.compile(r"github\.com/([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)")


def _firefox_cookies() -> dict:
    for c in glob.glob(os.path.expanduser("~/Library/Application Support/Firefox/Profiles/*/cookies.sqlite")):
        try:
            con = sqlite3.connect(f"file:{c}?immutable=1", uri=True)
            rows = con.execute(
                "SELECT name,value FROM moz_cookies WHERE host LIKE '%x.com' OR host LIKE '%twitter.com'"
            ).fetchall()
            con.close()
        except sqlite3.Error:
            continue
        d = {n: v for n, v in rows}
        if "auth_token" in d and "ct0" in d:
            return d
    return {}


def _links(t) -> list[str]:
    out = []
    for link in (getattr(t, "links", None) or []):
        u = getattr(link, "url", None)
        if u and "x.com" not in u and "twitter.com" not in u and "pic." not in u:
            out.append(u)
    return out


def _eng(t) -> dict:
    return {"author": t.user.username, "likes": t.likeCount, "retweets": t.retweetCount,
            "replies": t.replyCount, "views": getattr(t, "viewCount", None)}


def _to_signals(t, query: str, explode_min: int) -> list[Signal]:
    links = _links(t)
    if len(links) >= explode_min:                 # listicle → one signal per embedded link
        via = f"https://x.com/{t.user.username}/status/{t.id}"
        return [
            Signal(url=u, title=(_GH.search(u).group(1) if _GH.search(u) else u), source="x",
                   clean_text=t.rawContent[:500], captured=now_iso(),
                   meta={**_eng(t), "query": query, "via_tweet": via, "exploded": True})
            for u in links
        ]
    url = f"https://x.com/{t.user.username}/status/{t.id}"
    return [Signal(url=url, title=t.rawContent[:200], source="x", clean_text=t.rawContent,
                   captured=now_iso(), meta={**_eng(t), "query": query})]


async def _collect(cfg: dict) -> list[Signal]:
    from twscrape import API

    ck = _firefox_cookies()
    if not ck:
        raise RuntimeError("no x.com cookies in Firefox — log into x.com in Firefox")
    cookie_str = "; ".join(f"{k}={v}" for k, v in ck.items())

    api = API(ACCOUNTS_DB)
    user = cfg.get("account", "cerebro_x")
    try:
        await api.pool.delete_accounts([user])    # refresh cookies each run
    except Exception:  # noqa: BLE001
        pass
    await api.pool.add_account(user, "x", "x@x.com", "x", cookies=cookie_str)
    await api.pool.login_all()

    explode_min = cfg.get("explode_min_links", 3)
    per = cfg.get("per_query", 12)
    min_likes = cfg.get("min_likes", 0)
    out: list[Signal] = []
    seen: set[str] = set()

    def push(sigs):
        for s in sigs:
            if s.url not in seen:
                seen.add(s.url)
                out.append(s)

    for term in cfg.get("search_terms", []):      # search: drop low-engagement noise
        try:
            async for t in api.search(term, limit=per):
                if (t.likeCount or 0) < min_likes:
                    continue
                push(_to_signals(t, term, explode_min))
        except Exception:  # noqa: BLE001
            continue
    for handle in cfg.get("accounts", []):         # curators/follows: keep all their tweets
        try:
            u = await api.user_by_login(handle)
            if not u:
                continue
            async for t in api.user_tweets(u.id, limit=per):
                push(_to_signals(t, f"@{handle}", explode_min))
        except Exception:  # noqa: BLE001
            continue
    return out


def fetch(cfg: dict, settings) -> list[Signal]:
    try:
        return asyncio.run(_collect(cfg))
    except Exception:  # noqa: BLE001 — stale cookies / X change → skip, like the bird-fail path
        return []
