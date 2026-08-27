"""F033/F037 — `repos[]`: the notable-repos card, populated from one REST call per dev.

WHAT THIS LANE IS FOR. e01 froze `repos[]` in the record and shipped it `[]` with a
sibling `repos_populated: false`, because every element field the freeze names (title,
description, language, topics, stars_fact, last_push) needs REST repo endpoints e01
deliberately did not call. This is that lane, and it is the last piece of the record
that was ever a placeholder.

    GET /users/{login}/repos?per_page=100&sort=updated&direction=desc

One call returns every field, so the lane is exactly one call per PUBLISHED dev.

SELECTION IS OWNERSHIP AND RECENCY. NEVER MAGNITUDE. F033's verdict is "stars as a
displayed fact only, never a sort key", F021 forbids volume ordering outright, and
`tests/test_no_composite.py` fails any sort key touching `stars`/`stargazers_count`.
So the rule is: keep repos this login OWNS, that are not forks and not archived, in the
order the API already returned them (`sort=updated`, i.e. recency), capped at
`MAX_REPOS_PER_DEV`. `stargazers_count` is read exactly ONCE, to fill `stars_fact`, and
is never a filter, a comparator or a sort key. A test proves the selection returns the
identical set when every star count in the payload is zeroed.

WHY IT IS BUDGETED, WITH THE ARITHMETIC. 1,316 published devs is 1,316 cold calls on top
of e02's measured 1,744, which is 3,060 against a 2,400 kill criterion. So:

  * `RepoBudget(cap)` — a hard, shared, per-run ceiling, spent in F063 recurrence order
    so a truncated run spends its calls where the corpus keeps pointing;
  * a 168-hour cache TTL on a SECOND client, because repo metadata does not change
    hourly and a 24h TTL would re-buy the whole corpus every morning for nothing. A
    weekly TTL means a cold first run populates the cap, the next two finish the corpus,
    and the steady state is roughly corpus/7 calls a day;
  * `repos_populated` per record, true ONLY where the call for that login actually
    returned. Every dev the budget did not reach keeps `false`, and e04 renders no repo
    card for them — which is exactly the branch e01 introduced the marker for.

`first_seen` IS THE VAULT'S, NOT GITHUB'S. It is the earliest `captured:` of a Signal
note citing that repo (`vault_seed.SeedRepo.first_seen`), and `null` when the vault never
cited it. It is NOT GitHub's `created_at`: the field means "when the vault first saw
this", and a page that says otherwise is wrong about a fact.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The one path this module calls. Registered in `fanout.PUBLIC_READ_PATHS` so the F053
#: boundary sweep keeps covering it.
USER_REPOS_PATH = "/users/{login}/repos"

#: How many repos a profile shows. A display cap, not a quality judgement: the API
#: returned them in recency order and this keeps the most recent few.
MAX_REPOS_PER_DEV = 6

#: One page, the same bound the fan-out lane uses.
PER_PAGE = 100

#: A WEEK. Repo metadata (description, language, topics, last push) does not change
#: hourly, and the default 24h TTL would re-buy a 1,300-dev corpus every morning.
REPO_CACHE_TTL_HOURS = 168

#: The default per-run ceiling on this lane's calls. Sized so a cold first run plus the
#: 168h TTL walks the whole corpus in about three days and then costs corpus/7 a day.
DEFAULT_REPO_BUDGET = 500


@dataclass(frozen=True)
class RepoFact:
    """One repo, in the frozen `repos[]` element shape. Facts only.

    `stars_fact` and NOT `stars`: the name is frozen, and the difference is the whole
    ruling. `tests/test_no_composite.py`'s `BANNED_FIELDS` would fail this dataclass on
    a field named `stars` or `stargazers_count`, and the site's own no-composite test
    fails if any comparator over there ever reads it.
    """

    name: str
    title: str
    description: str | None
    language: str | None
    topics: tuple[str, ...]
    stars_fact: int | None
    first_seen: str | None
    last_push: str | None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "language": self.language,
            "topics": list(self.topics),
            "stars_fact": self.stars_fact,
            "first_seen": self.first_seen,
            "last_push": self.last_push,
        }


class RepoBudget:
    """A hard, shared, decrementing ceiling on this run's repo calls.

    Mirrors `fork_provenance.ForkBudget` deliberately: shared across the whole publish
    set rather than held per dev, because a per-dev bound multiplied by an uncapped
    corpus is not a bound. On exhaustion the lane stops and SAYS SO — `repos_populated`
    stays false for everybody it did not reach, and the budget artifact carries
    `repo_budget_exhausted` beside a non-zero `repos_unpopulated`.
    """

    def __init__(self, cap: int = DEFAULT_REPO_BUDGET):
        self.cap = max(0, int(cap))
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def take(self) -> bool:
        """Claim one call. False when there is nothing left to claim."""
        if self.exhausted:
            return False
        self.used += 1
        return True


def select(login: str, payload) -> tuple[dict, ...]:
    """The repos a profile shows, from one raw API page. PURE, and star-blind.

    Ownership, then not-a-fork, then not-archived, then the cap — applied in the order
    the API returned them, which is `pushed_at` recency. Nothing here reads
    `stargazers_count`, and `tests/test_repo_facts.py` proves the output is identical
    when every star count in the payload is zeroed.
    """
    low = (login or "").strip().lstrip("@").lower()
    out: list[dict] = []
    for row in payload if isinstance(payload, list) else ():
        if not isinstance(row, dict):
            continue
        if row.get("fork") or row.get("archived"):
            continue
        owner = ((row.get("owner") or {}).get("login")
                 if isinstance(row.get("owner"), dict) else None)
        if owner is None:
            full = str(row.get("full_name") or "")
            owner = full.split("/", 1)[0] if "/" in full else ""
        if str(owner or "").strip().lower() != low:
            continue
        if not str(row.get("name") or "").strip():
            continue
        out.append(row)
        if len(out) >= MAX_REPOS_PER_DEV:
            break
    return tuple(out)


def to_fact(row: dict, *, first_seen_by_repo: dict | None = None) -> RepoFact:
    """One API row -> one frozen fact.

    `title` IS THE REPO NAME. GitHub has no separate title field, the site defaults
    `title` to `name` anyway, and inventing a prettified title would be generated copy
    about a named person's project.
    """
    name = str(row.get("name") or "").strip()
    full = str(row.get("full_name") or "").strip()
    stars = row.get("stargazers_count")
    pushed = str(row.get("pushed_at") or "")
    topics = row.get("topics")
    return RepoFact(
        name=name,
        title=name,
        description=_text_or_none(row.get("description")),
        language=_text_or_none(row.get("language")),
        topics=tuple(str(t) for t in topics if str(t).strip())
        if isinstance(topics, list) else (),
        stars_fact=int(stars) if isinstance(stars, int) and not isinstance(stars, bool)
        else None,
        first_seen=(first_seen_by_repo or {}).get(full.lower()) or None,
        last_push=pushed[:10] or None,
    )


def facts_for(login: str, client, *, first_seen_by_repo=None, budget: RepoBudget):
    """`(facts, populated)` for one login. One REST call, or none at all.

    `populated` is TRUE ONLY WHEN THE CALL ACTUALLY RETURNED, and that is the point of
    returning it rather than inferring it from `len(facts)`:

        budget exhausted  -> ((), False)   nobody looked
        call raised       -> ((), False)   nobody looked; the exception does not escape
        call returned []  -> ((), True)    somebody looked; this person owns no repos
                                           the selection keeps

    Only the third is a fact about the person, and only the third may render a repo card.
    Collapsing the three would publish "this developer has no notable repos" about
    someone the run simply ran out of budget for.
    """
    if not budget.take():
        return (), False
    try:
        payload = client.request(USER_REPOS_PATH.format(login=login), {
            "per_page": PER_PAGE,
            "sort": "updated",
            "direction": "desc",
        })
    except Exception:  # noqa: BLE001 — one bad account must not sink the lane
        return (), False
    if not isinstance(payload, list):
        # A 404 (deleted account) or a malformed body. Nobody was successfully looked at,
        # so this is NOT "they have no repos".
        return (), False
    facts = tuple(to_fact(row, first_seen_by_repo=first_seen_by_repo)
                  for row in select(login, payload))
    return facts, True


def _text_or_none(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
