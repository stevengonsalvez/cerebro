# Cracked-Dev Registry Implementation Plan

## Overview
Turn "cracked devs" from a manual, GitHub-only, one-target-at-a-time CLI *generator* into a
maintained, curated **roster** (`config/cracked_devs.yaml`) that is the single source of truth for
who we track, and wire that roster into four ingestion lanes (X, GitHub, per-dev RSS, Reddit) plus
an identity-enrichment loop that resolves the same human across blog ↔ github ↔ x.

## Current State Analysis

What exists today (verified, with refs):

| Capability | State | Ref |
|---|---|---|
| `cracked-devs` CLI generator | Works. Manual, one repo/user at a time | `cerebro/__main__.py:35-50`, dispatch `:88-109` |
| GitHub intel + skill/entity/brief writers | Works | `cerebro/sink/cracked_devs.py:44,71,112` |
| Growth/momentum metrics + ranking | Works, but only ranks — never gates admission | `gitintel/metrics.py:11,41,71`, `rank.py:12,53` |
| Curated dev roster (tier/why/x/blog) | **Missing** | — |
| Watchlist reader `read_vault_watchlists()` | **Dead code.** No non-test caller; `vault/Watchlist/` does not even exist on disk | `gitintel/watchlists.py:24-29` |
| Cross-source identity (x + github + blog) | **Missing.** `identity_links` entity slot exists but nothing populates it | `sink/entities.py:111` |
| blog → github handle enrichment | **Missing** | — |
| Auto-promotion of hot devs into a list | **Missing** | — |

### Key Discoveries

- **The adapter contract is trivial to extend.** Every source is a module-level
  `def fetch(cfg: dict, settings) -> list[Signal]`, registered in a plain dict
  (`cerebro/sources/__init__.py:1-22`). Adding a source = new module + one dict entry + one
  `config/sources.yaml` block with `enabled: true`.
- **Source config is raw untyped dict.** `config.py:87` does `sources=_load("sources.yaml")`; each
  adapter reads via `cfg.get(...)`. No per-source dataclass to update.
- **`blog` and `twitter_username` are ALREADY FETCHED AND CACHED.** `GitHubClient.get_user`
  (`github_client.py:108`) returns the full raw `/users/{login}` payload, and every response is
  persisted verbatim to the sqlite `github_responses` table (`cache.py:12-17`, written at
  `github_client.py:68`). The fields are dropped only by the mapping in `user_from_api`
  (`profile_inspect.py:21`), which maps just `login, html_url, name, bio, followers, public_repos`.
  A repo-wide grep for `blog|twitter_username|website` returns **zero hits**.
  → **Identity linking is a field-mapping change, not a scraper.** This is the cheapest high-value
  win in the plan and is why Phase 2 is small.
- **`Signal` has typed tag layers** (`models.py:6-44`): `topic_tags`, `source_tags`, `entity_tags`,
  `artifact_tags`, `workflow_tags`, merged by `merge_tags()`. Roster-sourced signals should set
  `entity_tags=["developer/<login>"]` so they join the existing entity graph.
- **`per_source` stats are keyed by `Signal.source`, not registry name** (`orchestrator.py:34-35`).
  New sources must pick their `source=` string deliberately.
- **Orchestrator swallows per-source exceptions** (`orchestrator.py:24-27`) — one bad source cannot
  sink the run. New sources inherit this safety net.
- **`config.py:_load()` raises on a missing file** (`config.py:50-55`). The roster is optional, so it
  needs a tolerant loader; the precedent is `watchlists.read_watchlist` which returns `[]` when the
  file is absent (`watchlists.py:6-8`).
- **`rank_users` haystack is only `login + name + bio`** (`rank.py:56`). Any new profile field must
  be added there to influence coverage scoring.
- **No ruff, no mypy, no Makefile.** CI is `uv run pytest -q` only
  (`.github/workflows/tests.yml`), plus gitleaks/ggshield secret scanning. Tests are plain pytest,
  no conftest.py, network mocked by monkeypatching `requests.get` with a hand-rolled `DummyResp`
  (`tests/test_gitintel_client.py`), file-parsers tested with `tmp_path` fixtures
  (`tests/test_watchlists.py:6-19`).

## Desired End State

`config/cracked_devs.yaml` is a curated roster. On every pipeline run, the roster automatically
expands X accounts, per-dev blog feeds, tracked GitHub logins, and tracked Reddit users — no
hand-editing of `sources.yaml`. Running `python -m cerebro cracked-devs roster enrich` fills in
missing `github`/`x`/`blog` fields for existing entries by resolving identity across platforms, and
`... roster suggest` proposes new admissions from high-momentum devs already seen in signals.

Verify: add one dev to the roster with only a `github` handle → `roster enrich` fills in their blog
and x handle → next pipeline run ingests their tweets, their blog posts, and their new repos, and
their developer entity note shows populated **Identity Links**.

## What We're NOT Doing

- No new LLM calls in the roster path. Identity resolution is deterministic string/API matching, not
  model inference.
- No auto-admission. `roster suggest` only *proposes*; a human edits the YAML. No pipeline stage
  silently mutates the roster.
- No scraping of X profiles for identity. GitHub's `twitter_username` is the only x↔github link used.
- No backfill of historical signals against the new roster.
- No `--install` automation for skill bundles (`__main__.py:94-95` keeps that deliberately explicit).
- Not deleting `watchlists.py`. It stays for `git-search`; the roster does not replace it.
- No UI changes (`cerebro/ui/server.py` untouched).

## Implementation Approach

The roster is a **deep module with a shallow interface**: `cerebro/gitintel/roster.py` owns loading,
validation, tier filtering, and — critically — *merging itself into the raw sources dict at
config-load time*. That last choice means the existing `x` and `rss` adapters need **zero code
changes**: they simply receive a longer `accounts` / `feeds` list. Only genuinely new lanes
(github-devs, reddit-users) need new adapter modules.

```
┌──────────────────────────┐
│ config/cracked_devs.yaml │  roster = source of truth
└────────────┬─────────────┘
             │ load_roster()
             ▼
      ┌─────────────┐   apply_to_sources()   ┌──────────────────┐
      │ roster.py   │───────────────────────▶│ settings.sources │
      └──────┬──────┘                        └────────┬─────────┘
             │                                        │
             │                        ┌───────────────┼───────────────┐
             │                        ▼               ▼               ▼
             │                   x.accounts      rss.feeds     github_devs /
             │                   (no code chg)  (no code chg)  reddit_users
             │                                                 (new adapters)
             ▼
      ┌─────────────┐
      │ identity.py │  github get_user → blog + twitter_username
      └──────┬──────┘  → Identity Links on entity, → roster suggest
             ▼
      vault/Entities/developers/<login>.md
```

## Phase Dependency Graph

```
Wave 1: Phase 1 (roster core)      Phase 2 (identity fields)   -- parallel
Wave 2: Phase 3 (github_devs source)        depends on P1
Wave 3: Phase 4 (reddit_users source)       depends on P3  [serialized: shared __init__.py]
        Phase 5 (identity resolution)       depends on P1, P2
Wave 4: Phase 6 (CLI + entity links + docs) depends on P1, P2, P5
```

---

## Phase 1: Roster Core — schema, loader, source merge
<!-- wave: 1 | depends_on: [] | files: [config/cracked_devs.yaml, cerebro/gitintel/roster.py, cerebro/config.py, tests/test_roster.py] -->

### Overview
Create the roster file, a tolerant loader with a `CrackedDev` dataclass, and the merge that folds
roster handles into `settings.sources` at load time. After this phase the existing `x` and `rss`
sources already consume the roster with no changes to their code.

### Changes Required:

#### 1. The roster file
**File**: `config/cracked_devs.yaml` (new)
**Changes**: Curated roster. Seeded by migrating the 6 handles currently hardcoded at
`config/sources.yaml:69-74`. `wiring` lives in this file (not `sources.yaml`) so the roster is
self-contained.

```yaml
# Cracked devs — the curated roster. Single source of truth for who we track.
# Handles here are auto-merged into x.accounts / rss.feeds / github_devs / reddit_users at load.
version: 1

wiring:
  enabled: true
  feed_x: true          # merge `x` handles into sources.x.accounts
  feed_rss: true        # merge `blog_feed` URLs into sources.rss.feeds
  feed_github: true     # expose `github` logins to the github_devs source
  feed_reddit: true     # expose `reddit` handles to the reddit_users source
  max_tier: 2           # only devs with tier <= this are wired into sources

defaults:
  tier: 2
  enabled: true

devs:
  - name: Boris Cherny
    tier: 1
    x: bcherny
    github: bcherny
    blog: null
    blog_feed: null
    reddit: null
    tags: [claude-code, anthropic]
    why: "Claude Code creator — highest-signal source on Claude Code internals"
    added: "2026-07-20"
    discovered_via: seed

  - name: Pieter Levels
    tier: 1
    x: levelsio
    github: null
    blog: https://levels.io
    blog_feed: null
    reddit: null
    tags: [indiehacker, solo-founder, ship-fast]
    why: "Ships solo products at absurd velocity; the canonical vibe-coding operator"
    added: "2026-07-20"
    discovered_via: seed

  - name: Theo Browne
    tier: 1
    x: theo
    github: t3dotgg
    blog: null
    blog_feed: null
    reddit: null
    tags: [typescript, dx, t3-stack]
    why: "Loud, early, and usually right on TS/DX tooling shifts"
    added: "2026-07-20"
    discovered_via: seed

  - name: Matt Pocock
    tier: 1
    x: mattpocockuk
    github: mattpocock
    blog: null
    blog_feed: null
    reddit: null
    tags: [typescript, teaching]
    why: "Deepest practical TypeScript explainer; type-level idioms"
    added: "2026-07-20"
    discovered_via: seed

  - name: Skirano
    tier: 2
    x: skirano
    github: null
    blog: null
    blog_feed: null
    reddit: null
    tags: [ai-agents, demos]
    why: "Early hands-on agent demos, often before official docs exist"
    added: "2026-07-20"
    discovered_via: seed

  - name: Sentient Agency
    tier: 2
    x: sentient_agency
    github: null
    blog: null
    blog_feed: null
    reddit: null
    tags: [agentic-coding, curation]
    why: "Curator account — high hit-rate on agentic-coding links"
    added: "2026-07-20"
    discovered_via: seed

  - name: Simon Willison
    tier: 1
    x: simonw
    github: simonw
    blog: https://simonwillison.net
    blog_feed: https://simonwillison.net/atom/everything/
    reddit: null
    tags: [llm, datasette, tooling, prompt-injection]
    why: "Most reliable primary-source LLM analysis on the open web"
    added: "2026-07-20"
    discovered_via: seed   # feed already in sources.yaml rss.feeds — dedup must handle this
```

#### 2. Roster module
**File**: `cerebro/gitintel/roster.py` (new)
**Changes**: `CrackedDev` dataclass, tolerant loader, tier filter, and `apply_to_sources`. Public
interface is deliberately shallow: `load_roster()`, `apply_to_sources()`.

```python
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field, asdict
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DEFAULT_PATH = ROOT / "config" / "cracked_devs.yaml"


@dataclass
class CrackedDev:
    name: str
    tier: int = 2
    x: str = ""
    github: str = ""
    blog: str = ""
    blog_feed: str = ""
    reddit: str = ""
    tags: list[str] = field(default_factory=list)
    why: str = ""
    added: str = ""
    discovered_via: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def slug(self) -> str:
        """Stable identity key: github login wins, else x handle, else name."""
        return (self.github or self.x or self.name).strip().lstrip("@").lower()


def load_roster(path: str | pathlib.Path | None = None) -> tuple[list[CrackedDev], dict]:
    """Load the roster. Missing/empty file -> ([], default wiring). Never raises on absence.

    Precedent for tolerant load: gitintel/watchlists.py:6-8.
    """
    p = pathlib.Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return [], {"enabled": False}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [], {"enabled": False}

    wiring = dict(data.get("wiring") or {})
    wiring.setdefault("enabled", True)
    defaults = dict(data.get("defaults") or {})

    devs: list[CrackedDev] = []
    for raw in data.get("devs") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue  # name is the only hard requirement
        merged = {**defaults, **raw}
        devs.append(CrackedDev(
            name=name,
            tier=int(merged.get("tier") or 2),
            x=_handle(merged.get("x")),
            github=_handle(merged.get("github")),
            blog=_text(merged.get("blog")),
            blog_feed=_text(merged.get("blog_feed")),
            reddit=_handle(merged.get("reddit")),
            tags=[str(t) for t in (merged.get("tags") or [])],
            why=_text(merged.get("why")),
            added=_text(merged.get("added")),
            discovered_via=_text(merged.get("discovered_via")),
            enabled=bool(merged.get("enabled", True)),
        ))
    return devs, wiring


def active(devs: list[CrackedDev], wiring: dict) -> list[CrackedDev]:
    max_tier = int(wiring.get("max_tier") or 99)
    return [d for d in devs if d.enabled and d.tier <= max_tier]


def apply_to_sources(sources: dict, devs: list[CrackedDev], wiring: dict) -> dict:
    """Fold roster handles into the raw sources dict. Mutates and returns `sources`.

    Existing `x` and `rss` adapters need no code change — they just see longer lists.
    """
    if not wiring.get("enabled"):
        return sources
    picked = active(devs, wiring)

    if wiring.get("feed_x", True):
        x_cfg = sources.setdefault("x", {})
        x_cfg["accounts"] = _merge_unique(x_cfg.get("accounts") or [], [d.x for d in picked if d.x])

    if wiring.get("feed_rss", True):
        rss_cfg = sources.setdefault("rss", {})
        rss_cfg["feeds"] = _merge_unique(
            rss_cfg.get("feeds") or [], [d.blog_feed for d in picked if d.blog_feed]
        )

    # New lanes read their targets from the injected config (adapters land in Phase 3/4).
    if wiring.get("feed_github", True):
        gh = sources.setdefault("github_devs", {"enabled": False})
        gh["logins"] = _merge_unique(gh.get("logins") or [], [d.github for d in picked if d.github])

    if wiring.get("feed_reddit", True):
        rd = sources.setdefault("reddit_users", {"enabled": False})
        rd["users"] = _merge_unique(rd.get("users") or [], [d.reddit for d in picked if d.reddit])

    return sources


def by_github(devs: list[CrackedDev]) -> dict[str, CrackedDev]:
    return {d.github.lower(): d for d in devs if d.github}


def _merge_unique(existing: list, extra: list) -> list:
    """Case-insensitive dedup, preserving original order and original casing."""
    seen = {str(v).strip().lower() for v in existing}
    out = list(existing)
    for v in extra:
        key = str(v).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _handle(v: Any) -> str:
    return str(v).strip().lstrip("@") if v else ""


def _text(v: Any) -> str:
    return str(v).strip() if v else ""
```

#### 3. Wire into Settings
**File**: `cerebro/config.py`
**Changes**: Add a `cracked_devs` field to `Settings` (dataclass at `:31-46`), load the roster, and
apply the merge to the sources dict inside `load()` (which currently does `sources=_load("sources.yaml")`
at `:87`).

```python
# in the Settings dataclass (after `export`)
    cracked_devs: list = field(default_factory=list)
    cracked_devs_wiring: dict = field(default_factory=dict)

# in load(), replacing the bare `sources=_load("sources.yaml")` wiring:
    from .gitintel.roster import load_roster, apply_to_sources

    _sources = _load("sources.yaml")
    _devs, _wiring = load_roster()
    apply_to_sources(_sources, _devs, _wiring)
    # ... pass sources=_sources, cracked_devs=_devs, cracked_devs_wiring=_wiring
```

> Import is function-local to avoid a circular import (`gitintel.roster` must not import `config`).

#### 4. Trim the now-duplicated handles
**File**: `config/sources.yaml`
**Changes**: NOT touched in this phase — deliberately. The 6 handles stay in `x.accounts` during
Phase 1 so the merge's dedup path is exercised against real duplicates. They are removed in Phase 6
once the roster is proven to supply them.

#### 5. Tests
**File**: `tests/test_roster.py` (new)
**Changes**: Follow the `tests/test_watchlists.py:6-19` pattern — inline fixture via `tmp_path`.

```python
from __future__ import annotations

from cerebro.gitintel.roster import CrackedDev, apply_to_sources, load_roster, active


def _write(tmp_path, body):
    p = tmp_path / "cracked_devs.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_missing_file_returns_empty_and_disabled(tmp_path):
    devs, wiring = load_roster(tmp_path / "nope.yaml")
    assert devs == []
    assert wiring["enabled"] is False


def test_malformed_yaml_does_not_raise(tmp_path):
    p = _write(tmp_path, "devs: [ unclosed")
    devs, wiring = load_roster(p)
    assert devs == []
    assert wiring["enabled"] is False


def test_defaults_applied_and_handles_normalised(tmp_path):
    p = _write(tmp_path, """
version: 1
defaults:
  tier: 3
devs:
  - name: Test Dev
    x: "@handle"
    github: "  GhUser "
""")
    devs, _ = load_roster(p)
    assert devs[0].tier == 3
    assert devs[0].x == "handle"
    assert devs[0].github == "GhUser"
    assert devs[0].slug == "ghuser"


def test_entry_without_name_is_skipped(tmp_path):
    p = _write(tmp_path, "devs:\n  - x: ghost\n  - name: Real\n")
    devs, _ = load_roster(p)
    assert [d.name for d in devs] == ["Real"]


def test_max_tier_filters(tmp_path):
    p = _write(tmp_path, """
wiring: {max_tier: 1}
devs:
  - {name: A, tier: 1, x: a}
  - {name: B, tier: 2, x: b}
""")
    devs, wiring = load_roster(p)
    assert [d.name for d in active(devs, wiring)] == ["A"]


def test_apply_to_sources_merges_and_dedups_case_insensitively():
    devs = [
        CrackedDev(name="A", x="Alpha", blog_feed="https://a.dev/feed"),
        CrackedDev(name="B", x="beta", github="bee", reddit="bruser"),
    ]
    sources = {"x": {"accounts": ["alpha"]}, "rss": {"feeds": ["https://a.dev/feed"]}}
    out = apply_to_sources(sources, devs, {"enabled": True})
    assert out["x"]["accounts"] == ["alpha", "beta"]          # Alpha deduped, original casing kept
    assert out["rss"]["feeds"] == ["https://a.dev/feed"]      # exact dup dropped
    assert out["github_devs"]["logins"] == ["bee"]
    assert out["reddit_users"]["users"] == ["bruser"]


def test_wiring_disabled_is_a_noop():
    sources = {"x": {"accounts": ["only"]}}
    out = apply_to_sources(sources, [CrackedDev(name="A", x="new")], {"enabled": False})
    assert out["x"]["accounts"] == ["only"]


def test_selective_wiring_flags():
    devs = [CrackedDev(name="A", x="a", blog_feed="https://a/feed")]
    out = apply_to_sources({}, devs, {"enabled": True, "feed_x": True, "feed_rss": False})
    assert out["x"]["accounts"] == ["a"]
    assert out.get("rss", {}).get("feeds", []) == []
```

### Success Criteria:

#### Automated Verification:
- [ ] Tests pass: `uv run pytest -q`
- [ ] New roster tests pass: `uv run pytest tests/test_roster.py -q`
- [ ] Config loads with roster applied: `uv run python -c "from cerebro import config; s=config.load(); print(len(s.cracked_devs), s.sources['x']['accounts'])"`
- [ ] Roster YAML is valid: `uv run python -c "import yaml;yaml.safe_load(open('config/cracked_devs.yaml'))"`
- [ ] Existing 6 handles appear exactly once (no duplicates from the merge)
- [ ] Secret scan clean: `pre-commit run --all-files`

#### Manual Verification:
- [ ] Deleting `config/cracked_devs.yaml` still lets the full pipeline run (tolerant load)
- [ ] Setting `wiring.enabled: false` produces the pre-roster behaviour exactly

---

## Phase 2: GitHub identity fields — surface `blog` / `twitter_username`
<!-- wave: 1 | depends_on: [] | files: [cerebro/gitintel/models.py, cerebro/gitintel/profile_inspect.py, cerebro/gitintel/rank.py, tests/test_profile_identity.py] -->

### Overview
The GitHub users API already returns `blog`, `twitter_username`, `company`, `location`, and the raw
payload is already cached. Stop dropping them. This is the enabling change for all identity linking
and costs zero extra API calls.

### Changes Required:

#### 1. Add fields to the dataclasses
**File**: `cerebro/gitintel/models.py`
**Changes**: Add to `GitHubUserCandidate` (`:38`) and `ProfileInspection` (`:73`). Append at the end
of each dataclass so existing positional construction is unaffected.

```python
# GitHubUserCandidate — append:
    blog: str = ""
    twitter_username: str = ""
    company: str = ""
    location: str = ""

# ProfileInspection — append the same four fields.
```

#### 2. Map them through
**File**: `cerebro/gitintel/profile_inspect.py`
**Changes**: `user_from_api` (`:21`) currently maps only `login, html_url, name, bio, followers,
public_repos`. Add the four fields. `inspect_profile` (`:33`) must carry them onto `ProfileInspection`.

```python
def user_from_api(data: dict, track: str = "semantic") -> GitHubUserCandidate:
    return GitHubUserCandidate(
        login=data.get("login", ""),
        url=data.get("html_url", ""),
        name=data.get("name") or "",
        bio=data.get("bio") or "",
        followers=int(data.get("followers") or 0),
        public_repos=int(data.get("public_repos") or 0),
        track=track,
        blog=_clean_url(data.get("blog")),
        twitter_username=(data.get("twitter_username") or "").strip().lstrip("@"),
        company=(data.get("company") or "").strip(),
        location=(data.get("location") or "").strip(),
    )


def _clean_url(v) -> str:
    """GitHub `blog` is user-typed: often bare-domain, sometimes empty, sometimes junk."""
    s = (v or "").strip()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    return s
```

#### 3. Feed identity into ranking
**File**: `cerebro/gitintel/rank.py`
**Changes**: `rank_users` builds its haystack from `login + name + bio` only (`:56`). Include
`company` and `blog` so a query like "datasette" matches a dev whose blog domain says so.

```python
# in rank_users, extend the haystack construction:
    haystack = " ".join([c.login, c.name, c.bio, getattr(c, "company", ""), getattr(c, "blog", "")]).lower()
```

> `getattr` with a default keeps this safe if a caller passes an older-shaped object.

#### 4. Tests
**File**: `tests/test_profile_identity.py` (new)

```python
from __future__ import annotations

from cerebro.gitintel.profile_inspect import user_from_api


def test_identity_fields_are_mapped():
    u = user_from_api({
        "login": "simonw", "html_url": "https://github.com/simonw",
        "name": "Simon Willison", "bio": "…", "followers": 1, "public_repos": 2,
        "blog": "simonwillison.net", "twitter_username": "@simonw",
        "company": "@datasette", "location": "SF",
    })
    assert u.blog == "https://simonwillison.net"   # bare domain gets a scheme
    assert u.twitter_username == "simonw"          # leading @ stripped
    assert u.company == "@datasette"
    assert u.location == "SF"


def test_missing_identity_fields_default_empty():
    u = user_from_api({"login": "x", "html_url": "u"})
    assert (u.blog, u.twitter_username, u.company, u.location) == ("", "", "", "")


def test_null_blog_does_not_become_https_none():
    assert user_from_api({"login": "x", "blog": None}).blog == ""
```

### Success Criteria:

#### Automated Verification:
- [ ] Tests pass: `uv run pytest -q`
- [ ] New tests pass: `uv run pytest tests/test_profile_identity.py -q`
- [ ] Existing gitintel tests still pass: `uv run pytest tests/test_gitintel_client.py tests/test_growth_metrics.py -q`
- [ ] Conformance suite passes: `uv run pytest tests/test_conformance.py -q`

#### Manual Verification:
- [ ] `python -m cerebro cracked-devs user simonw --dry-run` output JSON contains a non-empty `blog` and `twitter_username`
- [ ] No extra GitHub API calls are made (verify cache hit count unchanged)

---

## Phase 3: `github_devs` source — track roster devs' GitHub activity
<!-- wave: 2 | depends_on: [1] | files: [cerebro/sources/github_devs.py, cerebro/sources/__init__.py, config/sources.yaml, tests/test_source_github_devs.py] -->

### Overview
New pipeline source: for each roster GitHub login, emit signals for their recently-pushed public
repos. Consumes the `logins` list that Phase 1's `apply_to_sources` injects.

### Changes Required:

#### 1. The adapter
**File**: `cerebro/sources/github_devs.py` (new)
**Changes**: Follow the `rss.py:12-23` template exactly. Reuse `GitHubClient.get_user_repos`
(`github_client.py:111`) so caching, auth, and the token-partitioned cache key all come for free.

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..gitintel.github_client import GitHubClient, GitHubClientError
from ..models import Signal
from .base import now_iso


def fetch(cfg: dict, settings) -> list[Signal]:
    logins = [str(x).strip().lstrip("@") for x in (cfg.get("logins") or []) if str(x).strip()]
    if not logins:
        return []

    per_dev = int(cfg.get("per_dev", 5))
    window_days = int(cfg.get("window_days", 14))
    min_stars = int(cfg.get("min_stars", 0))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    client = GitHubClient(settings)
    out: list[Signal] = []
    for login in logins:
        try:
            repos = client.get_user_repos(login, limit=per_dev * 3)
        except GitHubClientError:
            continue  # one dev failing must not kill the source
        kept = 0
        for r in repos or []:
            if kept >= per_dev:
                break
            if r.get("fork") or r.get("archived"):
                continue
            if int(r.get("stargazers_count") or 0) < min_stars:
                continue
            pushed = _parse(r.get("pushed_at"))
            if not pushed or pushed < cutoff:
                continue
            full = r.get("full_name") or ""
            out.append(Signal(
                url=r.get("html_url") or f"https://github.com/{full}",
                title=f"{full} — {(r.get('description') or '').strip()}".strip(" —"),
                source="github",              # keys per_source alongside trending/ossinsight
                captured=now_iso(),
                clean_text=(r.get("description") or "")[:2000],
                topic_tags=[str(t) for t in (r.get("topics") or [])],
                source_tags=["github/cracked-dev"],
                entity_tags=[f"developer/{login}", f"repo/{full}"],
                meta={
                    "dev": login, "full_name": full,
                    "stars": r.get("stargazers_count") or 0,
                    "language": r.get("language") or "",
                    "pushed_at": r.get("pushed_at") or "",
                    "published": r.get("pushed_at") or "",
                },
            ))
            kept += 1
    return out


def _parse(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
```

> `source="github"` is chosen deliberately: `orchestrator.py:34-35` keys `per_source` by
> `Signal.source`, and the existing convention folds `github_trending` + `ossinsight` into `github`.

#### 2. Register it
**File**: `cerebro/sources/__init__.py`
**Changes**: Add the import and one dict entry.

```python
from . import (
    github_devs, github_search, github_trending, gmail, hackernews, ossinsight,
    reddit, rss, seed_urls, showhn, x_twscrape, yclaunches, ycrfs,
)

SOURCES = {
    ...
    "github_devs": github_devs.fetch,
}
```

#### 3. Config block
**File**: `config/sources.yaml`
**Changes**: Add the block. `logins` is intentionally left empty — Phase 1's merge fills it.

```yaml
github_devs:            # roster devs' recent repo activity — `logins` auto-filled from cracked_devs.yaml
  enabled: true
  per_dev: 5            # max repos per dev per run
  window_days: 14       # only repos pushed within this window
  min_stars: 0          # raise to filter noise from scratch repos
```

#### 4. Tests
**File**: `tests/test_source_github_devs.py` (new)
**Changes**: Monkeypatch `GitHubClient.get_user_repos` (no network), per the
`tests/test_gitintel_client.py` mocking convention.

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cerebro.sources import github_devs


def _repo(name, days_ago=1, **kw):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    base = {"full_name": name, "html_url": f"https://github.com/{name}",
            "description": "d", "pushed_at": ts, "stargazers_count": 10,
            "fork": False, "archived": False, "topics": ["ai"], "language": "Python"}
    base.update(kw)
    return base


def _patch(monkeypatch, repos):
    monkeypatch.setattr(github_devs.GitHubClient, "__init__", lambda self, s=None: None)
    monkeypatch.setattr(github_devs.GitHubClient, "get_user_repos",
                        lambda self, login, limit=20: repos)


def test_empty_logins_short_circuits(monkeypatch):
    assert github_devs.fetch({"logins": []}, SimpleNamespace()) == []


def test_emits_signal_with_entity_tags(monkeypatch):
    _patch(monkeypatch, [_repo("simonw/datasette")])
    sigs = github_devs.fetch({"logins": ["simonw"]}, SimpleNamespace())
    assert len(sigs) == 1
    assert sigs[0].source == "github"
    assert "developer/simonw" in sigs[0].entity_tags
    assert "repo/simonw/datasette" in sigs[0].entity_tags


def test_forks_archived_and_stale_are_dropped(monkeypatch):
    _patch(monkeypatch, [
        _repo("a/fork", fork=True),
        _repo("a/arch", archived=True),
        _repo("a/stale", days_ago=90),
        _repo("a/good"),
    ])
    sigs = github_devs.fetch({"logins": ["a"], "window_days": 14}, SimpleNamespace())
    assert [s.meta["full_name"] for s in sigs] == ["a/good"]


def test_min_stars_filter(monkeypatch):
    _patch(monkeypatch, [_repo("a/small", stargazers_count=1), _repo("a/big", stargazers_count=99)])
    sigs = github_devs.fetch({"logins": ["a"], "min_stars": 50}, SimpleNamespace())
    assert [s.meta["full_name"] for s in sigs] == ["a/big"]


def test_per_dev_cap(monkeypatch):
    _patch(monkeypatch, [_repo(f"a/r{i}") for i in range(10)])
    assert len(github_devs.fetch({"logins": ["a"], "per_dev": 3}, SimpleNamespace())) == 3


def test_client_error_on_one_dev_does_not_kill_source(monkeypatch):
    def boom(self, login, limit=20):
        if login == "bad":
            raise github_devs.GitHubClientError("429")
        return [_repo("ok/repo")]
    monkeypatch.setattr(github_devs.GitHubClient, "__init__", lambda self, s=None: None)
    monkeypatch.setattr(github_devs.GitHubClient, "get_user_repos", boom)
    sigs = github_devs.fetch({"logins": ["bad", "ok"]}, SimpleNamespace())
    assert [s.meta["dev"] for s in sigs] == ["ok"]
```

### Success Criteria:

#### Automated Verification:
- [ ] Tests pass: `uv run pytest -q`
- [ ] New source tests pass: `uv run pytest tests/test_source_github_devs.py -q`
- [ ] Source is registered: `uv run python -c "from cerebro.sources import SOURCES; assert 'github_devs' in SOURCES"`
- [ ] Logins auto-populate: `uv run python -c "from cerebro import config; print(config.load().sources['github_devs']['logins'])"` is non-empty
- [ ] Health check reports the source: `python -m cerebro health`

#### Manual Verification:
- [ ] A dry-run produces github signals attributed to roster devs, tagged `developer/<login>`
- [ ] Rate limit is not exhausted with the full roster (check `client.rate_limit` remaining)

### Checkpoints:
- **`[CHECKPOINT:human-verify]`**: Review signal quality before adding more lanes
  - What was built: roster → GitHub activity ingestion
  - How to verify: 1) `python -m cerebro run --dry-run` 2) open the scratch briefing
    3) confirm roster-dev repos appear and are not overwhelmingly noisy
  - Resume: Type "approved" or describe the noise problem so `min_stars` / `per_dev` can be tuned

---

## Phase 4: `reddit_users` source — track roster devs on Reddit
<!-- wave: 3 | depends_on: [3] | files: [cerebro/sources/reddit_users.py, cerebro/sources/__init__.py, config/sources.yaml, tests/test_source_reddit_users.py] -->

### Overview
Per-user Reddit submissions for roster devs who have a `reddit` handle. Serialized after Phase 3
purely because both phases edit `cerebro/sources/__init__.py` and `config/sources.yaml`.

### Changes Required:

#### 1. The adapter
**File**: `cerebro/sources/reddit_users.py` (new)
**Changes**: Mirror `reddit.py:22-38` closely, including its two hard-won constraints.

> **CONSTRAINT — do not "improve" this to the JSON API.** `reddit.py:10-11` carries a `ponytail:`
> note: *"Reddit 403s the .json API for unauthenticated clients and rate-limits (429) its RSS when
> hit in bursts. Space requests + honor Retry-After once."* So this adapter uses the `.rss`
> endpoint and reuses `reddit._get(url, limit)` (note: **two** positional args) plus the 2-second
> inter-request sleep from `reddit.py:27-28`.

> **Consequence**: the RSS payload carries no score, so a `min_score` filter is **not possible**
> here. Volume is bounded by `limit` alone. If score filtering ever becomes necessary it needs an
> authenticated Reddit client, which is out of scope.

```python
from __future__ import annotations

import time

import feedparser

from ..models import Signal
from .base import now_iso
from .reddit import _get   # reuse the existing 429/Retry-After handling — signature: _get(url, limit)


def fetch(cfg: dict, settings) -> list[Signal]:
    users = [_clean(u) for u in (cfg.get("users") or []) if str(u).strip()]
    users = [u for u in users if u]
    if not users:
        return []

    limit = int(cfg.get("limit", 10))
    out: list[Signal] = []
    for i, user in enumerate(users):
        if i:
            time.sleep(2)   # same burst-avoidance spacing as reddit.py:27-28
        try:
            r = _get(f"https://www.reddit.com/user/{user}/submitted/.rss", limit)
        except Exception:  # noqa: BLE001 — one suspended/404 user must not kill the source
            continue
        if r.status_code != 200:
            continue
        for e in feedparser.parse(r.content).entries[:limit]:
            out.append(Signal(
                url=e.get("link", ""),
                title=e.get("title", ""),
                source="reddit",
                captured=now_iso(),
                source_tags=["reddit/cracked-dev"],
                entity_tags=[f"developer/{user}"],
                meta={"dev": user, "published": e.get("published", "")},
            ))
    return out


def _clean(v) -> str:
    s = str(v).strip().lstrip("@")
    return s[2:] if s.lower().startswith("u/") else s
```

> `.lstrip("u/")` would be a bug — `lstrip` strips a *character set*, so a handle like `"uuu_dev"`
> or `"user123"` would be mangled. Hence the explicit `_clean` prefix check above.

#### 2. Register it
**File**: `cerebro/sources/__init__.py`
**Changes**: Add `reddit_users` to the import tuple and `"reddit_users": reddit_users.fetch` to `SOURCES`.

#### 3. Config block
**File**: `config/sources.yaml`

```yaml
reddit_users:           # roster devs' reddit submissions — `users` auto-filled from cracked_devs.yaml
  enabled: true
  limit: 10             # posts per dev; no score filter possible (RSS carries no score — see adapter note)
```

#### 4. Tests
**File**: `tests/test_source_reddit_users.py` (new)
**Changes**: Monkeypatch `reddit_users._get` to return a stub with `.status_code` and `.content`
(RSS bytes), matching the `DummyResp` convention in `tests/test_gitintel_client.py`. Also
monkeypatch `time.sleep` to keep the suite fast.

Cases:
- empty `users` short-circuits without any HTTP call
- `u/name` and `@name` both normalise to `name`; `"uuu_dev"` is **not** mangled (regression guard for
  the `lstrip` trap called out above)
- non-200 status is skipped silently
- an exception on one user does not prevent later users from being fetched
- emitted signals have `source == "reddit"` and `entity_tags` containing `developer/<user>`
- `limit` caps the entries taken per dev

### Success Criteria:

#### Automated Verification:
- [ ] Tests pass: `uv run pytest -q`
- [ ] New tests pass: `uv run pytest tests/test_source_reddit_users.py -q`
- [ ] Registered: `uv run python -c "from cerebro.sources import SOURCES; assert 'reddit_users' in SOURCES"`
- [ ] No import cycle: `uv run python -c "import cerebro.sources"`

#### Manual Verification:
- [ ] A roster dev with a reddit handle yields their recent posts in a dry run
- [ ] A roster dev with `reddit: null` is silently skipped, no error

---

## Phase 5: Identity resolution — blog ↔ github ↔ x
<!-- wave: 3 | depends_on: [1, 2] | files: [cerebro/gitintel/identity.py, tests/test_identity.py] -->

### Overview
Deterministic resolution of the same human across platforms, plus the "when we catalog a blog, find
their github handle too" loop you asked for. No new dependency and — for the primary path — no new
API calls, because Phase 2 already surfaces `blog` and `twitter_username` from the cached payload.

Resolution runs in two directions:

```
github login ──get_user──▶ blog + twitter_username     (free, cached, authoritative)
blog/feed URL ──match──▶ github login                  (reverse index, then HTML fallback)
```

### Changes Required:

#### 1. Identity module
**File**: `cerebro/gitintel/identity.py` (new)
**Changes**: Three public functions — `resolve_from_github`, `resolve_from_blog`, `identity_links`.

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .github_client import GitHubClient, GitHubClientError
from .profile_inspect import user_from_api
from .roster import CrackedDev

GITHUB_HREF = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/?(?:[\"'<\s]|$)")
RESERVED = {
    "features", "pricing", "about", "login", "join", "explore", "topics",
    "trending", "marketplace", "sponsors", "orgs", "settings", "apps", "blog",
    "readme", "security", "enterprise", "team", "customer-stories", "collections",
}


@dataclass
class Identity:
    github: str = ""
    x: str = ""
    blog: str = ""
    confidence: str = "none"   # high | medium | low | none
    evidence: str = ""


def resolve_from_github(login: str, client: GitHubClient) -> Identity:
    """Authoritative direction: GitHub's own profile fields. No extra API cost (cached)."""
    try:
        data = client.get_user(login)
    except GitHubClientError:
        return Identity(confidence="none", evidence="github api error")
    if not data:
        return Identity(confidence="none", evidence="no such user")
    u = user_from_api(data)
    return Identity(
        github=u.login, x=u.twitter_username, blog=u.blog,
        confidence="high",
        evidence=f"github.com/{u.login} profile fields",
    )


def resolve_from_blog(blog_url: str, client: GitHubClient, *, fetch_page=None) -> Identity:
    """Reverse direction: find the github handle behind a blog we decided to catalog.

    Order: (1) github.io subdomain, (2) github.com link in the page HTML,
    (3) GitHub user search by blog domain. Stops at the first confident hit.
    """
    if not blog_url:
        return Identity(confidence="none")
    host = (urlparse(blog_url).hostname or "").lower()

    # 1. <login>.github.io is a free, unambiguous answer.
    if host.endswith(".github.io"):
        login = host.rsplit(".github.io", 1)[0].split(".")[-1]
        if login:
            return Identity(github=login, blog=blog_url, confidence="high",
                            evidence=f"{host} is a github pages domain")

    # 2. Scrape the homepage for a github.com/<login> link.
    if fetch_page is not None:
        html = fetch_page(blog_url) or ""
        for m in GITHUB_HREF.finditer(html):
            login = m.group(1)
            if login.lower() in RESERVED:
                continue
            return Identity(github=login, blog=blog_url, confidence="medium",
                            evidence=f"github.com/{login} linked from {host}")

    # 3. Ask GitHub who claims this domain as their blog.
    try:
        res = client.search_users(f"{host} in:blog", limit=5) or {}
    except GitHubClientError:
        return Identity(blog=blog_url, confidence="none", evidence="user search failed")
    items = res.get("items") or []
    if len(items) == 1:
        return Identity(github=items[0].get("login", ""), blog=blog_url, confidence="medium",
                        evidence=f"sole github user with blog={host}")
    if len(items) > 1:
        return Identity(blog=blog_url, confidence="low",
                        evidence=f"{len(items)} github users claim blog={host} — ambiguous")
    return Identity(blog=blog_url, confidence="none", evidence=f"no github user claims {host}")


def merge_into(dev: CrackedDev, ident: Identity, *, overwrite: bool = False) -> tuple[CrackedDev, list[str]]:
    """Fill blank roster fields from a resolved identity. Returns (dev, list-of-changed-fields).

    Never overwrites a curated value unless `overwrite` is set — a human's entry wins over a guess.
    """
    changed: list[str] = []
    for field_name, value in (("github", ident.github), ("x", ident.x), ("blog", ident.blog)):
        if not value:
            continue
        current = getattr(dev, field_name)
        if current and not overwrite:
            continue
        if current == value:
            continue
        setattr(dev, field_name, value)
        changed.append(field_name)
    return dev, changed


def identity_links(dev: CrackedDev) -> list[dict]:
    """Render roster identity as the `identity_links` payload entities.py:111 expects.

    Contract per sink/entities.py:306 `_link`: label from title|name, url, detail from reason.
    """
    out = []
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
```

#### 2. Tests
**File**: `tests/test_identity.py` (new)
**Changes**: No network. Inject a fake client object and a `fetch_page` callable.

```python
from __future__ import annotations

from cerebro.gitintel.identity import Identity, identity_links, merge_into, resolve_from_blog, resolve_from_github
from cerebro.gitintel.roster import CrackedDev


class FakeClient:
    def __init__(self, user=None, search=None):
        self._user, self._search = user, search or {"items": []}
    def get_user(self, login):
        return self._user
    def search_users(self, q, limit=10):
        return self._search


def test_resolve_from_github_is_high_confidence():
    c = FakeClient(user={"login": "simonw", "html_url": "u", "blog": "simonwillison.net",
                         "twitter_username": "simonw"})
    i = resolve_from_github("simonw", c)
    assert (i.github, i.x, i.blog, i.confidence) == ("simonw", "simonw", "https://simonwillison.net", "high")


def test_github_pages_domain_resolves_without_network():
    i = resolve_from_blog("https://bcherny.github.io/posts/1", FakeClient())
    assert i.github == "bcherny" and i.confidence == "high"


def test_html_link_resolution_skips_reserved_paths():
    html = '<a href="https://github.com/features">f</a><a href="https://github.com/realdev">me</a>'
    i = resolve_from_blog("https://x.dev", FakeClient(), fetch_page=lambda u: html)
    assert i.github == "realdev" and i.confidence == "medium"


def test_sole_blog_domain_claimant_is_medium():
    i = resolve_from_blog("https://a.dev", FakeClient(search={"items": [{"login": "solo"}]}))
    assert i.github == "solo" and i.confidence == "medium"


def test_ambiguous_domain_yields_low_confidence_and_no_handle():
    i = resolve_from_blog("https://a.dev", FakeClient(search={"items": [{"login": "a"}, {"login": "b"}]}))
    assert i.github == "" and i.confidence == "low"


def test_merge_never_clobbers_curated_values():
    dev = CrackedDev(name="A", github="curated")
    dev, changed = merge_into(dev, Identity(github="guess", x="newx"))
    assert dev.github == "curated"      # human wins
    assert dev.x == "newx"              # blank field filled
    assert changed == ["x"]


def test_merge_overwrite_flag():
    dev, changed = merge_into(CrackedDev(name="A", github="old"), Identity(github="new"), overwrite=True)
    assert dev.github == "new" and changed == ["github"]


def test_identity_links_shape_matches_entities_contract():
    links = identity_links(CrackedDev(name="A", github="g", x="h", blog="https://b"))
    assert {l["title"] for l in links} == {"github/g", "x/h", "blog"}
    assert all("url" in l and "reason" in l for l in links)
```

### Success Criteria:

#### Automated Verification:
- [ ] Tests pass: `uv run pytest -q`
- [ ] New tests pass: `uv run pytest tests/test_identity.py -q`
- [ ] No network in tests: `uv run pytest tests/test_identity.py -q` passes with networking disabled
- [ ] `identity_links()` output renders through the real writer without error

#### Manual Verification:
- [ ] `resolve_from_github("simonw", real_client)` returns blog + x with `confidence="high"`
- [ ] An ambiguous blog domain returns `confidence="low"` rather than a wrong handle

---

## Phase 6: CLI surface, entity links, roster cleanup, docs
<!-- wave: 4 | depends_on: [1, 2, 5] | files: [cerebro/__main__.py, cerebro/sink/cracked_devs.py, config/sources.yaml, README.md, tests/test_cli_roster.py] -->

### Overview
Make the roster operable: `roster list|enrich|suggest`, populate `identity_links` on developer entity
notes, remove the now-duplicated inline X handles, and document the whole thing.

### Changes Required:

#### 1. `roster` subcommand
**File**: `cerebro/__main__.py`
**Changes**: Extend the existing `cracked-devs` subparser (`:35-50`) with a third kind. Dispatch
alongside the `repo`/`user` branches at `:88-109`. Output JSON like the existing commands so it stays
scriptable and testable via `capsys` (the `tests/test_cli_cracked_devs.py:14-68` pattern).

```python
    cd_roster = cd_sub.add_parser("roster", help="inspect and enrich the cracked-dev roster")
    cd_roster.add_argument("action", choices=["list", "enrich", "suggest"])
    cd_roster.add_argument("--tier", type=int, default=None, help="filter to tier <= N")
    cd_roster.add_argument("--write", action="store_true",
                           help="write enrichment back to config/cracked_devs.yaml")
    cd_roster.add_argument("--overwrite", action="store_true",
                           help="let resolution replace curated values (default: fill blanks only)")
    cd_roster.add_argument("--limit", type=int, default=20, help="suggest: max candidates")
```

- `list` → the roster as JSON, with a `wired` block showing exactly what each lane received.
- `enrich` → for every dev with a `github`, `resolve_from_github`; for every dev with a `blog` but no
  `github`, `resolve_from_blog`. Report a diff. Only writes the YAML when `--write` is passed.
- `suggest` → read recent `developer/*` entity notes + `github_search` candidates, rank by
  `momentum_score` (`metrics.py:41`), exclude anyone already in the roster (match on
  `CrackedDev.slug`), print the top N as paste-ready YAML blocks.

> **Round-trip safety**: `--write` must preserve comments and key order. Rewriting with `yaml.dump`
> would destroy the curated `why:` comments. Implement the write as a targeted line-level patch of
> only the changed scalar fields, and assert round-trip fidelity in a test.

#### 2. Populate `identity_links` on the developer entity
**File**: `cerebro/sink/cracked_devs.py`
**Changes**: When writing a developer entity for a login that is in the roster, attach
`identity_links(dev)` (Phase 5) plus `why`/`tier` so the currently-empty **Identity Links** section
(`sink/entities.py:111`) renders. `entities._get` accepts a Mapping or an object, so passing a dict
with an `identity_links` key is sufficient — no change to `entities.py`.

#### 3. Remove the duplicated inline handles
**File**: `config/sources.yaml`
**Changes**: Now that Phase 1 supplies them, delete the 6 hardcoded entries from `x.accounts`
(`:69-74`) and leave a pointer comment.

```yaml
  accounts: []          # sourced from config/cracked_devs.yaml — add devs there, not here
```

> Do this only after verifying Phase 1's merge produces the identical list, so the change is a no-op
> in behaviour. Capture the before/after list in the phase's manual verification.

#### 4. Docs
**File**: `README.md`
**Changes**: New "Cracked-dev roster" section: what the roster is, the four lanes it feeds, how to add
a dev (minimum viable entry is `name` + one handle), the enrich/suggest workflow, and the tier policy
(tier 1 = read everything, tier 2 = wired but filtered, tier 3 = tracked but not ingested).

#### 5. Tests
**File**: `tests/test_cli_roster.py` (new)
**Changes**: Follow `tests/test_cli_cracked_devs.py:14-68` — monkeypatch `config.load`, set
`sys.argv`, call `main()`, parse `capsys` JSON.

Cases: `list` emits every dev and the `wired` block; `enrich` without `--write` mutates nothing on
disk; `enrich --write` fills only blank fields; `enrich --write` **preserves comments and key order**
(round-trip fidelity assertion); `suggest` excludes devs already on the roster; `--tier` filters.

### Success Criteria:

#### Automated Verification:
- [ ] Tests pass: `uv run pytest -q`
- [ ] CLI tests pass: `uv run pytest tests/test_cli_roster.py -q`
- [ ] `python -m cerebro cracked-devs roster list` emits valid JSON
- [ ] `python -m cerebro cracked-devs roster enrich` (no `--write`) leaves the file byte-identical
- [ ] Round-trip: after `enrich --write`, `git diff config/cracked_devs.yaml` shows only changed scalar values, no comment loss and no re-ordering
- [ ] Full suite green: `uv run pytest -q`
- [ ] Secret scan clean: `pre-commit run --all-files`

#### Manual Verification:
- [ ] `x.accounts` resolved list is byte-identical before and after the Phase 6.3 cleanup
- [ ] A developer entity note in the vault shows a populated **Identity Links** section
- [ ] `roster suggest` proposes plausible devs, none of them already on the roster

### Checkpoints:
- **`[CHECKPOINT:human-verify]`**: Roster curation quality
  - What was built: full roster CLI, identity links, docs
  - How to verify: 1) `python -m cerebro cracked-devs roster list --tier 1`
    2) `python -m cerebro cracked-devs roster suggest --limit 10`
    3) judge whether the suggestions are actually "cracked" or just high-follower
  - Resume: Type "approved", or say which suggestions are bad so the ranking weights can be tuned

---

## Testing Strategy

### Unit Tests
- Roster loader: missing file, malformed YAML, missing `name`, defaults merge, handle normalisation
  (`@x` → `x`), tier filtering.
- Merge: case-insensitive dedup preserving original casing, per-lane wiring flags, disabled no-op.
- Identity: each resolution path and each confidence level; `merge_into` never clobbers curated values.
- Sources: empty-input short-circuit, filters (fork/archived/stale/min_stars), per-dev caps,
  single-target failure isolation, handle normalisation without `lstrip` character-set mangling.

### Integration Tests
- `config.load()` end-to-end with a real roster file → assert `sources["x"]["accounts"]`,
  `sources["rss"]["feeds"]`, `sources["github_devs"]["logins"]`, `sources["reddit_users"]["users"]`.
- Orchestrator run with the new sources mocked → assert `per_source` counts and no unhandled
  exception escapes (`orchestrator.py:24-27`).
- Conformance suite (`tests/test_conformance.py`) must stay green — it guards the Signal contract.

### Manual Testing Steps
1. `python -m cerebro run --dry-run`; open `vault/_scratch/` and confirm roster-dev signals appear.
2. Add a dev with only `github:` set → `roster enrich --write` → confirm `blog` and `x` are filled.
3. Add a dev with only `blog:` set → `roster enrich` → confirm the github handle resolves, or that it
   honestly reports `low`/`none` confidence rather than guessing.
4. Set `wiring.enabled: false` → confirm behaviour is identical to pre-roster.
5. Delete `config/cracked_devs.yaml` → confirm the pipeline still runs clean.

## Performance Considerations

- **GitHub rate limit is the real constraint.** `github_devs` costs one `get_user_repos` call per
  roster dev per run; `roster enrich` costs one `get_user` per dev. The client has read-through
  caching (`github_client.py:41-46`, 24h default TTL) but **no throttling or backoff**
  (`:58-63` is observational only). At ~30 devs this is ~30 calls/run, comfortably inside the
  authenticated 5000/hr budget. Above ~200 devs, add backoff before scaling the roster.
- `max_tier` is the pressure valve: keep tier-3 devs catalogued but unwired.
- Roster load is a single small YAML parse at startup — negligible.
- Sources already run concurrently in a `ThreadPoolExecutor` (`orchestrator.py:30`), so the two new
  lanes add no wall-clock beyond their own latency.

## Migration Notes

- `config/cracked_devs.yaml` is optional by design; absence degrades to today's behaviour exactly.
- The 6 inline X handles live in **both** places between Phase 1 and Phase 6.3. This is deliberate —
  it exercises the dedup path against real duplicates. Phase 6.3 removes the inline copies only after
  the resolved list is verified byte-identical.
- `vault/Watchlist/` still does not exist and is still unwired. Out of scope; `watchlists.py` stays
  for `git-search`. If a vault-side roster *view* is wanted later, generate it from the YAML — do not
  make the markdown authoritative.
- No state/DB migration. No changes to the sqlite schema.

## Resuming on Another Machine

```bash
git fetch origin
git checkout plan/cracked-dev-registry
uv venv && uv pip install -e ".[dev]"
uv run pytest -q                 # confirm green baseline before starting
```

Then start with Wave 1 (Phase 1 and Phase 2 are independent and can run in parallel), or hand this
file to `/implement`, which parses the `<!-- wave: ... -->` comments and `[CHECKPOINT:*]` markers.

Environment needed: `GITHUB_TOKEN` in `.env` (read via `github.token_env`,
`github_client.py:21`) — without it the GitHub lanes fall back to the 60/hr anonymous limit and
Phase 3/5 manual verification will rate-limit.

## References

- Existing generator CLI: `cerebro/__main__.py:35-50`, dispatch `:88-109`
- Source registry + adapter contract: `cerebro/sources/__init__.py:1-22`, template `cerebro/sources/rss.py:12-23`
- Signal model: `cerebro/models.py:6-44`
- Settings + YAML loading: `cerebro/config.py:31-46`, `:50-55`, `:87`
- Orchestrator dispatch and error isolation: `cerebro/orchestrator.py:20-38`
- GitHub client (already caches `blog`/`twitter_username`): `cerebro/gitintel/github_client.py:40-68`, `:108`
- Field-mapping chokepoint that drops them: `cerebro/gitintel/profile_inspect.py:21`
- Ranking haystack: `cerebro/gitintel/rank.py:53-56`
- Growth/momentum metrics: `cerebro/gitintel/metrics.py:11,41,71`
- Developer entity + `identity_links` slot: `cerebro/sink/entities.py:24`, `:105-115`, `_link` `:306`
- Dead watchlist reader (not the source of truth): `cerebro/gitintel/watchlists.py:24-29`
- Test conventions: `tests/test_cli_cracked_devs.py:14-68`, `tests/test_watchlists.py:6-19`, `tests/test_gitintel_client.py`
- CI commands: `.github/workflows/tests.yml` (`uv run pytest -q`)
