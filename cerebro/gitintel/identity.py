from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from .github_client import GitHubClient, GitHubClientError
from .profile_inspect import user_from_api
from .roster import CrackedDev

# Matches a github.com/<login> link. Login rules: 1-39 chars, alnum or hyphen,
# no leading/trailing hyphen. Trailing boundary keeps us from swallowing paths.
GITHUB_HREF = re.compile(
    r"https?://(?:www\.)?github\.com/"
    r"([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)"
    r"/?(?:[\"'<\s]|$)"
)

# Paths under github.com that are not user logins — skip these when scraping.
RESERVED = {
    "features", "pricing", "about", "login", "join", "explore", "topics",
    "trending", "marketplace", "sponsors", "orgs", "settings", "apps", "blog",
    "readme", "security", "enterprise", "team", "customer-stories", "collections",
    "notifications", "new", "search", "contact",
}


@dataclass
class Identity:
    """Resolved cross-platform identity for one human. `confidence` is one of
    high | medium | low | none; `evidence` explains how it was derived."""

    github: str = ""
    x: str = ""
    blog: str = ""
    confidence: str = "none"
    evidence: str = ""


def resolve_from_github(login: str, client: GitHubClient) -> Identity:
    """Forward direction: GitHub's user API is free, cached and authoritative.
    It hands us the blog + twitter_username the human self-declared."""
    try:
        data = client.get_user(login)
    except GitHubClientError:
        return Identity(confidence="none", evidence="github api error")
    if not data:
        return Identity(confidence="none", evidence=f"no github user {login}")
    u = user_from_api(data)
    return Identity(
        github=u.login,
        x=u.twitter_username,
        blog=u.blog,
        confidence="high",
        evidence=f"github.com/{u.login} api profile",
    )


def resolve_from_blog(
    blog_url: str,
    client: GitHubClient,
    fetch_page: Callable[[str], str] | None = None,
) -> Identity:
    """Reverse direction: given a blog we decided to catalog, find its github login.

    Order: (1) <login>.github.io subdomain, (2) github.com link in page HTML,
    (3) GitHub user search by blog domain. Stops at the first confident hit and
    honestly reports low/none rather than guessing on ambiguity.
    """
    if not blog_url:
        return Identity(confidence="none")
    host = (urlparse(blog_url).hostname or "").lower()

    # 1. <login>.github.io is a free, unambiguous answer.
    if host.endswith(".github.io"):
        login = host.rsplit(".github.io", 1)[0].split(".")[-1]
        if login:
            return Identity(
                github=login, blog=blog_url, confidence="high",
                evidence=f"{host} github pages domain",
            )

    # 2. Scrape the homepage for a github.com/<login> link.
    if fetch_page is not None:
        html = fetch_page(blog_url) or ""
        for m in GITHUB_HREF.finditer(html):
            login = m.group(1)
            if login.lower() in RESERVED:
                continue
            return Identity(
                github=login, blog=blog_url, confidence="medium",
                evidence=f"github.com/{login} linked from {host}",
            )

    # 3. Ask GitHub who claims this domain as their blog.
    try:
        res = client.search_users(f"{host} in:blog", limit=5) or {}
    except GitHubClientError:
        return Identity(blog=blog_url, confidence="none", evidence="user search failed")
    items = res.get("items") or []
    if len(items) == 1:
        return Identity(
            github=items[0].get("login", ""), blog=blog_url, confidence="medium",
            evidence=f"sole github user for blog={host}",
        )
    if len(items) > 1:
        return Identity(
            blog=blog_url, confidence="low",
            evidence=f"{len(items)} github users claim blog={host} — ambiguous",
        )
    return Identity(
        blog=blog_url, confidence="none",
        evidence=f"no github user for blog={host}",
    )


def merge_into(dev: CrackedDev, ident: Identity) -> tuple[CrackedDev, list[str]]:
    """Fill empty roster fields from a resolved Identity. Never overwrites an
    existing value — curated data wins. Returns (dev, list-of-changed-fields)."""
    changed: list[str] = []
    for field_name, value in (("github", ident.github), ("x", ident.x), ("blog", ident.blog)):
        if value and not getattr(dev, field_name):
            setattr(dev, field_name, value)
            changed.append(field_name)
    return dev, changed


def identity_links(dev: CrackedDev) -> list[dict]:
    """Build identity-link records for a developer entity note. Shape matches the
    Identity Links slot (sink/entities.py:111), rendered by _link (:306)."""
    out: list[dict] = []
    if dev.github:
        out.append({"title": f"github/{dev.github}", "url": f"https://github.com/{dev.github}",
                    "reason": "GitHub profile"})
    if dev.x:
        out.append({"title": f"x/{dev.x}", "url": f"https://x.com/{dev.x}", "reason": "X account"})
    if dev.blog:
        out.append({"title": "blog", "url": dev.blog, "reason": "Personal site"})
    if dev.blog_feed:
        out.append({"title": "feed", "url": dev.blog_feed, "reason": "RSS/Atom feed"})
    if dev.reddit:
        out.append({"title": f"reddit/u/{dev.reddit}", "url": f"https://www.reddit.com/user/{dev.reddit}",
                    "reason": "Reddit profile"})
    return out
