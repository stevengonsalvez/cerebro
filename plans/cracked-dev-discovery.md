# Cracked-Dev Auto-Discovery (crackscan) — Implementation Plan

Spec: `plans/cracked-dev-discovery-spec.md`. Turns "hot repo → who built it → are they
cracked → track them" into a `crackscan` source: 4 seeds → human filter → two-stage score
→ auto-add tier 3. Offline-buildable (GitHub API monkeypatched in tests, per
`tests/test_gitintel_client.py` `DummyResp` convention). Live verification needs a token,
deferred to a human checkpoint.

## Current State (verified)

| Capability | State | Ref |
|---|---|---|
| Star-velocity repo scan | Works | `sources/github_trending.py`, `sources/ossinsight.py` |
| Dev follower-growth metrics | Works | `gitintel/metrics.py:41` `enrich_user_metrics` |
| Portfolio momentum | Works | `gitintel/metrics.py:71` `portfolio_momentum` |
| GitHubClient `token=` override | Works | `github_client.py:22` ctor already accepts `token` |
| `get_user`/`get_user_repos`/`search_users` | Works | `github_client.py:79,108,111` |
| identity resolution (x/reddit→github) | Works | `gitintel/identity.py` (shipped) |
| repo-owner → human resolution | **Missing** | — |
| events-API commit-rate | **Missing** | no `/users/{u}/events` call exists |
| human/org/bot filter | **Missing** | — |
| crackedness scorer | **Missing** | — |
| auto-admit tier 3 | **Missing** | — |
| per-source token env | **Partial** | ctor takes `token=`, but no source resolves its own env |

### Key constraints (from spec + code)
- Tests mock `requests.get`/client methods — no network. Token B only for live checkpoint.
- Adapter contract: `def fetch(cfg: dict, settings) -> list[Signal]`, registered in `sources/__init__.py`.
- Orchestrator swallows per-source exceptions (`orchestrator.py:24-27`) — crackscan inherits safety.
- Roster admit must be comment/order-preserving line append (same rule as `roster enrich --write`,
  `__main__.py` `_yaml_scalar_out` + line patch shipped in PR #12).
- tier 3 is `max_tier`-gated → admitted devs are tracked-but-unwired. Safe to auto-add.
- Signal `source=` string chosen deliberately (`orchestrator.py:34-35` keys `per_source` by it).

---

## Phase 1: Per-source GitHub token resolution
<!-- wave: 1 | depends_on: [] | files: [cerebro/gitintel/github_client.py, tests/test_client_token_env.py] -->

### Overview
Let a source request its own token env (isolation + separate rate ceiling) with fallback to
the default. `GitHubClient.__init__` already accepts `token=`; add a small resolver so a source
can do `GitHubClient(settings, token=resolve_token(cfg, settings))`.

### Changes
**File**: `cerebro/gitintel/github_client.py`
Add module-level helper:
```python
def resolve_token(cfg: dict | None, settings=None) -> str | None:
    """Per-source token: cfg['token_env'] wins, else settings.github.token_env, else GITHUB_TOKEN.
    Returns the env VALUE (or None if that specific env is unset, so ctor falls back)."""
    gh = getattr(settings, "github", {}) or {}
    env_name = (cfg or {}).get("token_env") or gh.get("token_env") or "GITHUB_TOKEN"
    val = os.environ.get(env_name)
    return val if val else None
```
> Returning None (not "") lets `GitHubClient.__init__`'s existing `token is not None` guard fall
> through to its own env read — so an unset crackscan token degrades to the default token cleanly.

**File**: `tests/test_client_token_env.py` (new)
- `resolve_token({"token_env": "GITHUB_TOKEN_CRACKSCAN"}, settings)` reads that env when set (monkeypatch `os.environ`).
- Unset crackscan env → returns None (fallback path).
- No `token_env` in cfg → falls to `settings.github.token_env` → `GITHUB_TOKEN`.

### Success Criteria
- [ ] `uv run pytest tests/test_client_token_env.py -q`
- [ ] Full suite still green: `uv run pytest -q`

---

## Phase 2: Owner resolution + human filter
<!-- wave: 1 | depends_on: [] | files: [cerebro/gitintel/owner_resolve.py, tests/test_owner_resolve.py] -->

### Overview
Resolve a repo `full_name` to the human who built it, and filter orgs/bots/empty accounts.
Pure functions taking a client — fully mockable.

### Changes
**File**: `cerebro/gitintel/owner_resolve.py` (new)
```python
VENDOR_ORGS = {"google","microsoft","vercel","facebook","aws","amazon","apple",
               "netflix","cloudflare","openai","anthropic","github","gitlab", ...}

def is_human(user: dict) -> bool:
    """Reject org/bot/empty. user = github user payload."""
    if (user.get("type") or "").lower() != "user":
        return False
    login = (user.get("login") or "").lower()
    if login.endswith("[bot]") or login in VENDOR_ORGS:
        return False
    # require at least one human signal
    return bool((user.get("name") or "").strip() or (user.get("bio") or "").strip())

def resolve_owner(full_name: str, client) -> str | None:
    """repo 'owner/name' -> human login. If owner is an org, fall to top human committer.
    Returns login or None if no human found."""
    owner = full_name.split("/")[0]
    u = client.get_user(owner)
    if u and is_human(u):
        return u.get("login")
    # org / non-human owner: try top committers
    try:
        contribs = client.get_repo_contributors(full_name, limit=5)   # new client method
    except Exception:
        return None
    for c in contribs:
        cu = client.get_user(c.get("login", ""))
        if cu and is_human(cu):
            return cu.get("login")
    return None
```
Also add `GitHubClient.get_repo_contributors(full_name, limit)` →
`request(f"/repos/{full_name}/contributors", {"per_page": limit})` returning list.
(Add to `github_client.py` — this phase owns that one method addition; Phase 1 owns `resolve_token`.
To avoid two phases editing github_client.py in the same wave, put `get_repo_contributors` HERE and
keep Phase 1 limited to the module-level `resolve_token` function — different regions, but if the
executor detects a conflict, Phase 2 may instead call `client.request(...)` inline and skip the method.)

> DEDUP NOTE for executors: Phase 1 and Phase 2 both may touch `github_client.py`. Phase 2's
> `get_repo_contributors` is optional sugar — if coordination is unclear, Phase 2 calls
> `client.request(f"/repos/{full}/contributors", {"per_page": 5})` inline and does NOT edit
> `github_client.py`. That keeps the wave conflict-free. Prefer the inline form.

**File**: `tests/test_owner_resolve.py` (new) — FakeClient injecting user payloads.
Cases:
- human user owner → returns login.
- `type: Organization` owner → falls to top human committer.
- `[bot]` login → filtered.
- vendor org login → filtered.
- empty (no name/bio) → filtered.
- org with no human contributors → None.

### Success Criteria
- [ ] `uv run pytest tests/test_owner_resolve.py -q`
- [ ] `is_human` rejects Organization, [bot], vendor, empty; accepts real user
- [ ] Full suite green

---

## Phase 3: Crackedness scorer (cheap + deep)
<!-- wave: 2 | depends_on: [1] | files: [cerebro/gitintel/crackscore.py, cerebro/gitintel/github_client.py, tests/test_crackscore.py] -->

### Overview
Score a candidate login. Stage A (cheap): follower growth + portfolio momentum + ships-a-lot,
from cached payload + snapshots. Stage B (deep): commit-rate/day from events API — only called
for top-N. Reuses `metrics.enrich_user_metrics` + `metrics.portfolio_momentum`.

### Changes
**File**: `cerebro/gitintel/github_client.py`
Add `get_user_events(login, pages=1)` → `request(f"/users/{login}/events", {"per_page": 100})`
(list). One method; if wave-conflict with Phase 1, executor may inline via `request` in crackscore.

**File**: `cerebro/gitintel/crackscore.py` (new)
```python
@dataclass
class CrackScore:
    login: str
    score: float
    commits_per_day: float = 0.0
    followers_gained_30d: int = 0
    portfolio_momentum: float = 0.0
    ships_score: float = 0.0
    deep: bool = False
    reason: str = ""

def cheap_score(login, client, cache, *, captured_at=None) -> CrackScore:
    """Stage A: no events call. followers 0.25 + portfolio 0.25 + ships 0.15 (renormalised)."""
    # build GitHubUserCandidate from client.get_user, enrich_user_metrics for follower growth,
    # get_user_repos -> portfolio_momentum, ships = f(public_repos, push recency, acct age)

def deep_score(base: CrackScore, client, *, window_days=90, now=None) -> CrackScore:
    """Stage B: add commits_per_day from PushEvents in window, weight 0.35, recombine."""
    # events = client.get_user_events(login); count PushEvent payload.commits over window / days

WEIGHTS = {"commit": 0.35, "follower": 0.25, "portfolio": 0.25, "ships": 0.15}
```
- `ships_score`: `min(log10(public_repos+1)/2,1)*0.5 + push_recency*0.3 + young_high_output*0.2`.
- Deterministic: pass `now` in (no `Date.now()`); tests inject fixed timestamps.
- commit-rate: count commits across `PushEvent` entries (`payload.size` or `len(payload.commits)`)
  with `created_at` inside window, ÷ window_days.

**File**: `tests/test_crackscore.py` (new) — FakeClient + fixed `now`.
Cases:
- cheap_score combines the three cheap signals, `deep=False`.
- deep_score adds commit-rate, `deep=True`, score shifts up for a high-commit dev.
- zero-history candidate → cheap signals only, no crash.
- events with non-PushEvent entries ignored.
- commits outside window excluded.

### Success Criteria
- [ ] `uv run pytest tests/test_crackscore.py -q`
- [ ] Scores deterministic (fixed `now`), in [0,1]
- [ ] Full suite green

---

## Phase 4: crackscan source — seeds, funnel, admit
<!-- wave: 3 | depends_on: [1, 2, 3] | files: [cerebro/sources/crackscan.py, cerebro/gitintel/roster.py, cerebro/sources/__init__.py, config/sources.yaml, tests/test_source_crackscan.py] -->

### Overview
The integration: gather candidate logins from 4 seeds → human filter → cheap-score all →
deep-score top-N → admit score≥threshold (max admit_max/scan) as tier 3, dedup by slug,
comment-safe YAML append. Rest logged as considered.

### Changes
**File**: `cerebro/sources/crackscan.py` (new)
`fetch(cfg, settings) -> list[Signal]`:
1. token = `resolve_token(cfg, settings)`; `client = GitHubClient(settings, token=token)`.
2. Seeds (each guarded, empty-safe):
   - **hot repos**: read recent `github`-source signals' repos OR re-list trending — MVP: take
     logins already injected by roster into `github_devs` PLUS repos from `cfg.get("seed_repos", [])`.
     (Seed plumbing kept simple; richer wiring is a follow-up — `log`/note what's not yet mined.)
   - **vault repo notes**: scan `settings.vault_path/Entities/repos/*.md` front-matter for `full_name`.
   - **reddit/x authors**: for handles in `cfg.get("seed_handles", [])`, `identity.resolve_from_*`,
     accept confidence in {high, medium}.
   - **roster-repo contributors**: for each roster dev's github, top contributors of their top repo.
   - `resolve_owner` each repo → login; dedup all logins; drop anyone already on roster (by slug).
3. `is_human` filter (payload already fetched during resolve).
4. cheap_score all → sort → `deep_score` top `cfg.get("top_n", 10)` (budget guard: skip deep if
   `client.rate_limit['remaining']` below `cfg.get("min_remaining", 200)`).
5. Admit: score ≥ `cfg.get("score_threshold", 0.55)`, cap `cfg.get("admit_max", 5)` → append tier-3
   entries to roster YAML via `roster.append_devs(...)`; rest → emit a Signal each tagged
   `crackscan/considered` so they surface without polluting the roster.
6. Emit one Signal per admitted dev (`source="github"`, `source_tags=["crackscan/admitted"]`,
   `entity_tags=[f"developer/{login}"]`, meta with score breakdown).

**File**: `cerebro/gitintel/roster.py`
Add `append_devs(path, devs: list[dict]) -> list[str]`: comment/order-preserving append of new
tier-3 entries to `cracked_devs.yaml`; skip any whose slug already present; return added slugs.
Reuse the line-level write approach from `__main__.py` enrich (do NOT `yaml.dump` the whole file).

**File**: `cerebro/sources/__init__.py` — register `"crackscan": crackscan.fetch`.

**File**: `config/sources.yaml`
```yaml
crackscan:              # auto-discover cracked devs; auto-admits tier 3 to cracked_devs.yaml
  enabled: true
  token_env: GITHUB_TOKEN_CRACKSCAN   # falls back to GITHUB_TOKEN if unset
  top_n: 10             # deep commit-rate pass only on top N cheap-scorers
  admit_max: 5          # max new tier-3 devs per scan
  score_threshold: 0.55 # crackedness gate for admission
  window_days: 90       # commit-rate window
  min_remaining: 200    # skip deep pass if token budget below this
  seed_repos: []        # optional explicit repos to mine owners from
  seed_handles: []      # optional x/reddit handles to resolve→github
```

**File**: `tests/test_source_crackscan.py` (new) — FakeClient + tmp roster + fixed now.
Cases:
- empty seeds → no admits, no crash.
- org-owned seed repo → resolves human committer, admits the human not the org.
- candidate already on roster → excluded (dedup by slug).
- score below threshold → not admitted (but a `considered` Signal emitted).
- admit_max caps writes; extras logged.
- budget guard: low `rate_limit.remaining` → deep pass skipped, cheap scores still admit.
- `append_devs` preserves comments + order; new dev appears with `discovered_via: crackscan`.
- unset token → resolve_token None → client falls back (no crash).

### Success Criteria
- [ ] `uv run pytest tests/test_source_crackscan.py -q`
- [ ] `python -c "from cerebro.sources import SOURCES; assert 'crackscan' in SOURCES"`
- [ ] `python -c "import yaml; yaml.safe_load(open('config/sources.yaml'))"`
- [ ] roster round-trip: after append, `git diff config/cracked_devs.yaml` shows only added lines, no comment loss
- [ ] Full suite green

### Checkpoints
- **[CHECKPOINT:human-verify]** (live, needs token): set `GITHUB_TOKEN_CRACKSCAN`, run
  `python -m cerebro run --dry-run`, confirm crackscan admits plausible humans (no orgs/bots),
  commit-rate numbers sane, roster diff clean. Resume: "approved" or name bad admits to tune threshold.

---

## Phase 5: CLI surface + docs
<!-- wave: 4 | depends_on: [4] | files: [cerebro/__main__.py, README.md, tests/test_cli_discover.py] -->

### Overview
Make discovery inspectable: `roster list --discovered crackscan` filter, and document the whole
crackscan capability + the tier-3 auto-admit contract + token setup.

### Changes
**File**: `cerebro/__main__.py`
Add `--discovered <source>` filter to `roster list` (filter devs by `discovered_via`). JSON output,
testable via capsys per `tests/test_cli_roster.py` pattern.

**File**: `README.md`
New "Cracked-dev auto-discovery" subsection under the roster docs: what crackscan does, the 4 seeds,
the two-stage funnel, the human filter, tier-3 auto-admit (and why it's safe: unwired + prunable),
`GITHUB_TOKEN_CRACKSCAN` setup, and the tuning knobs (score_threshold, admit_max).

**File**: `tests/test_cli_discover.py` (new)
- `roster list --discovered crackscan` returns only crackscan-admitted devs.
- filter with no matches → empty list, valid JSON.

### Success Criteria
- [ ] `uv run pytest tests/test_cli_discover.py -q`
- [ ] `python -m cerebro cracked-devs roster list --discovered crackscan` emits valid JSON
- [ ] Full suite green
- [ ] Secret scan clean: `pre-commit run --all-files`

---

## Testing Strategy
- All GitHub calls mocked (FakeClient / monkeypatched `requests.get`), no network, deterministic `now`.
- Human filter: org/bot/vendor/empty rejection is the correctness core — cover every branch.
- Funnel: cheap-all → deep-top-N ordering; budget-guard skip; admit cap; dedup by slug.
- Roster append: comment/order preservation round-trip (assert on file text, not just parse).

## Wave / DAG
```
Wave 1:  P1 token-resolve  ∥  P2 owner+filter      (disjoint new files)
Wave 2:  P3 crackscore                              (depends P1)
Wave 3:  P4 crackscan source + admit                (depends P1,P2,P3)
Wave 4:  P5 CLI + docs                              (depends P4)
```

## Not Doing
- No LLM in scoring. No tier-1/2 auto-admit. No promotion logic. No X/Reddit profile scraping.
- No richer seed plumbing beyond MVP (explicit `seed_repos`/`seed_handles` + vault + roster-contrib);
  deeper trending-signal mining is a logged follow-up, not this plan.

## Resuming / Live verify
```bash
uv run pytest -q                     # offline baseline, must be green
# then, once token provided:
export GITHUB_TOKEN_CRACKSCAN=<token>
python -m cerebro run --dry-run      # Phase 4 checkpoint
```
