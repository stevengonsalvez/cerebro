from __future__ import annotations

import asyncio
import datetime
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
                "SELECT name,value FROM moz_cookies WHERE host='x.com' OR host LIKE '%.x.com'"
                " OR host='twitter.com' OR host LIKE '%.twitter.com'"
            ).fetchall()
            con.close()
        except sqlite3.Error:
            continue
        d = {n: v for n, v in rows}
        if "auth_token" in d and "ct0" in d:
            return d
    return {}


def _env_cookies() -> dict:
    """Portable fallback for machines without Firefox: X_AUTH_TOKEN + X_CT0 from env/.env."""
    at, ct0 = os.environ.get("X_AUTH_TOKEN"), os.environ.get("X_CT0")
    return {"auth_token": at, "ct0": ct0} if at and ct0 else {}


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


def _within(date, cutoff) -> bool:
    """tweet within the beast window. None date → keep (don't break the < comparison)."""
    if date is None:
        return True
    return date >= cutoff


async def _walk_thread(api, root, cfg, explode_min):
    extra_sigs, ctx = [], []
    n = cfg.get("beast_thread_replies", 15)
    try:
        async for r in api.tweet_replies(root.id, limit=n):
            ctx.append(f"@{r.user.username}: {r.rawContent}")     # text only — ignore media
            if _links(r):                                          # link-bearing reply → own signal(s)
                extra_sigs.extend(_to_signals(r, f"thread:{root.id}", explode_min))
    except Exception:  # noqa: BLE001 — thread fetch failure must not sink the tweet
        pass
    thread_text = ("\n\n— thread —\n" + "\n".join(ctx)) if ctx else ""
    return extra_sigs, thread_text


async def _collect(cfg: dict) -> list[Signal]:
    from twscrape import API

    ck = _firefox_cookies() or _env_cookies()
    if not ck:
        raise RuntimeError("no x.com cookies — log into x.com in Firefox, or set X_AUTH_TOKEN + X_CT0")
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

    if cfg.get("beast"):                          # firehose: every tweet in window, walk threads
        window = cfg.get("beast_window_hours", 24)
        beast_max_per = cfg.get("beast_max_per", 500)
        max_threads = cfg.get("beast_max_threads", 100)
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=window)
        walks = 0  # roots thread-walked so far (bounded by beast_max_threads request budget)

        async def ingest(t, query):
            nonlocal walks
            sigs = _to_signals(t, query, explode_min)   # NO min_likes filter in beast
            if (t.replyCount or 0) > 0 and walks < max_threads:
                walks += 1
                extra, thread_text = await _walk_thread(api, t, cfg, explode_min)
                # attach thread text only to a non-exploded root; an exploded tweet has no single
                # root signal to own it (sigs[0] is the first embedded link, not the tweet)
                if thread_text and sigs and not sigs[0].meta.get("exploded"):
                    sigs[0].clean_text += thread_text
                sigs += extra
            push(sigs)

        for term in cfg.get("search_terms", []):
            try:
                async for t in api.search(term, limit=beast_max_per, kv={"product": "Latest"}):
                    if not _within(getattr(t, "date", None), cutoff):
                        break                          # Latest → reverse-chron, first old tweet ends the page
                    await ingest(t, term)
            except Exception:  # noqa: BLE001
                continue
        for handle in cfg.get("accounts", []):
            try:
                u = await api.user_by_login(handle)
                if not u:
                    continue
                async for t in api.user_tweets(u.id, limit=beast_max_per):
                    if not _within(getattr(t, "date", None), cutoff):
                        continue   # user_tweets puts the pinned tweet first (often old) → skip, don't break; beast_max_per caps the scan
                    await ingest(t, f"@{handle}")
            except Exception:  # noqa: BLE001
                continue

        if cfg.get("beast_feed"):                 # your following-graph feed: expand who you follow
            handle = cfg.get("feed_account") or cfg.get("account", "")
            feed_cap = cfg.get("beast_feed_max_accounts", 150)
            try:
                me = await api.user_by_login(handle)
                follows = []
                if me:
                    async for u in api.following(me.id, limit=feed_cap):
                        follows.append(u)
                        if len(follows) >= feed_cap:  # bound the fan-out (one user_tweets call per follow)
                            break
                for u in follows:
                    try:
                        async for t in api.user_tweets(u.id, limit=beast_max_per):
                            if not _within(getattr(t, "date", None), cutoff):
                                continue
                            await ingest(t, f"feed:@{u.username}")   # dedup vs explicit accounts via `seen`
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001 — feed unavailable (stale cookies / handle change) → skip
                pass
        return out

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


if __name__ == "__main__":   # offline: no twscrape, no network
    from types import SimpleNamespace as NS

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=24)
    # (a) date-window predicate keeps recent / drops old, survives None
    assert _within(now - datetime.timedelta(hours=1), cutoff)       # recent → keep
    assert not _within(now - datetime.timedelta(hours=48), cutoff)  # old → drop
    assert _within(None, cutoff)                                    # None → keep, no crash

    # (b) link-bearing tweet with >=explode_min links explodes (one signal per link)
    t = NS(id=1, rawContent="three repos", user=NS(id=9, username="bob"),
           links=[NS(url="https://github.com/a/b"), NS(url="https://github.com/c/d"),
                  NS(url="https://example.com/x")],
           likeCount=5, retweetCount=1, replyCount=2, viewCount=10)
    sigs = _to_signals(t, "q", 3)
    assert len(sigs) == 3 and all(s.source == "x" for s in sigs), "3 links → 3 exploded signals"

    # (c) thread-text concatenation format
    ctx = ["@x: hi", "@y: yo"]
    assert ("\n\n— thread —\n" + "\n".join(ctx)) == "\n\n— thread —\n@x: hi\n@y: yo"
    print("x beast self-check OK")
