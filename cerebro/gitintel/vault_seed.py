"""F001 — the vault seed lane.

Mines the vault's own Signal notes for `github.com/{owner}/{repo}` references and
returns them as provenance-carrying seeds. This is the anchor lane: every candidate
the devs pipeline ever considers must be traceable back to at least one signal note
that already earned its place in the vault.

Pure function, no network, no GitHub client. Takes a path, returns data.

Measured against the real corpus (1,036 notes, 2026-08-26): 202 owner/repo pairs
across 175 distinct owners. Frontmatter `url:` alone yields 180/167; the body carries
the rest, so both are read. Zero GitHub reserved paths appear in the corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Non-repository first path segments on github.com. A `github.com/sponsors/foo`
#: link is not a repo and must never become a candidate owner.
#: T02t asserts this set's size equals the number of literals written here, so a
#: duplicate entry introduced by a later edit cannot silently swallow a real one.
GITHUB_RESERVED = frozenset({
    "sponsors", "orgs", "features", "topics", "apps", "marketplace", "settings",
    "login", "about", "collections", "explore", "trending", "users", "enterprise",
    "pricing", "readme", "search", "notifications", "blog", "security",
    "customer-stories", "site", "contact", "join", "new", "codespaces",
    "signup", "events", "sitemap.xml", "robots.txt", "account", "dashboard",
    "issues", "pulls", "stars", "watching", "organizations", "logout",
})

#: The number of literals written into GITHUB_RESERVED above. If a future edit
#: introduces a duplicate, the frozenset shrinks and this constant catches it.
_GITHUB_RESERVED_LITERALS = 38

_GITHUB_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38})?)/([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)

#: Punctuation that routinely trails a URL pasted into prose or a markdown link.
_TRAILING_JUNK = ").,;:!?'\"`>]}*_"


@dataclass(frozen=True)
class SeedRepo:
    """One `owner/name` pair with the provenance that put it in the pool."""

    owner: str
    name: str
    signal_hashes: tuple[str, ...]
    first_seen: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def key(self) -> str:
        return self.full_name.lower()


def seed_repos(vault_path) -> list[SeedRepo]:
    """Every distinct `owner/repo` referenced by the vault's Signal notes.

    Deduped case-insensitively on `owner/repo`, keeping first-seen casing and
    unioning the provenance of every note that mentions it. Deterministically
    ordered by the lowercased key so the artifact diffs cleanly run to run.
    """
    base = Path(vault_path) / "Signals"
    if not base.is_dir():
        return []

    acc: dict[str, dict] = {}
    for note in sorted(base.glob("*.md")):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        captured = _captured(text)
        stem = note.stem
        for owner, name in _extract(text):
            key = f"{owner.lower()}/{name.lower()}"
            entry = acc.get(key)
            if entry is None:
                acc[key] = {
                    "owner": owner,
                    "name": name,
                    "hashes": {stem},
                    "first_seen": captured,
                }
            else:
                entry["hashes"].add(stem)
                if captured and (not entry["first_seen"] or captured < entry["first_seen"]):
                    entry["first_seen"] = captured

    return [
        SeedRepo(
            owner=e["owner"],
            name=e["name"],
            signal_hashes=tuple(sorted(e["hashes"])),
            first_seen=e["first_seen"],
        )
        for _, e in sorted(acc.items())
    ]


def _extract(text: str) -> list[tuple[str, str]]:
    """All `owner/repo` pairs in one note, frontmatter `url:` and body alike."""
    out: list[tuple[str, str]] = []
    for owner, name in _GITHUB_URL_RE.findall(text):
        name = _clean_repo(name)
        if not name or not owner:
            continue
        if owner.lower() in GITHUB_RESERVED:
            continue
        if owner.endswith("-") or owner.startswith("-"):
            continue
        out.append((owner, name))
    return out


def _clean_repo(name: str) -> str:
    """Strip the query, fragment, `.git` suffix and trailing prose punctuation."""
    name = name.split("?", 1)[0].split("#", 1)[0]
    name = name.rstrip("/")
    while name and name[-1] in _TRAILING_JUNK:
        name = name[:-1]
    if name.lower().endswith(".git"):
        name = name[:-4]
    if name in {".", ".."}:
        return ""
    return name


def _captured(text: str) -> str:
    """The note's frontmatter `captured:` timestamp, or '' when absent."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        if key.strip() == "captured":
            return value.strip().strip('"')
    return ""
