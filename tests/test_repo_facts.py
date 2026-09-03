"""F033 — `repos[]`, and the two properties that make it publishable.

1. THE SELECTION IS STAR-BLIND. F033's verdict is "stars as a displayed fact only, never
   a sort key" and F021 forbids volume ordering outright. The test that proves it is not
   "no `sorted` mentions stars" — it is running the real selection twice, once on the
   real payload and once with every `stargazers_count` zeroed, and asserting the same
   repos come back in the same order.

2. `repos_populated` TELLS THE TRUTH. Three different situations produce an empty list,
   and only ONE of them is a fact about the person. Collapsing them would publish "this
   developer has no notable repos" about somebody the run simply ran out of budget for.
"""
from __future__ import annotations

import copy

from cerebro.gitintel import fanout, repo_facts


def _row(name, owner="simonw", *, stars=0, fork=False, archived=False, **over):
    row = {
        "name": name,
        "full_name": f"{owner}/{name}",
        "owner": {"login": owner},
        "fork": fork,
        "archived": archived,
        "stargazers_count": stars,
        "description": f"{name} description",
        "language": "Python",
        "topics": ["cli", "llm"],
        "pushed_at": "2026-08-20T11:22:33Z",
    }
    row.update(over)
    return row


#: Deliberately in an order that DISAGREES with the star counts, so "same set" and
#: "same order" are both real assertions.
PAYLOAD = [
    _row("llm", stars=3),
    _row("datasette", stars=9000),
    _row("sqlite-utils", stars=1),
    _row("shot-scraper", stars=50),
]


_DEFAULT = object()


class _Client:
    def __init__(self, payload=_DEFAULT, raises=False):
        # A sentinel, not `None`: `None` is what the real client returns on a 404 and is
        # one of the payloads under test here.
        self.payload = PAYLOAD if payload is _DEFAULT else payload
        self.raises = raises
        self.calls: list[tuple] = []

    def request(self, path, params=None):
        self.calls.append((path, params))
        if self.raises:
            raise RuntimeError("boom")
        return self.payload


# --- selection is ownership and recency, never magnitude ---------------------

def test_the_selection_is_identical_when_every_star_count_is_zeroed():
    """THE CENTRAL TEST OF THIS MODULE. If a star count ever became a filter or a
    comparator, this is what would go red."""
    zeroed = copy.deepcopy(PAYLOAD)
    for row in zeroed:
        row["stargazers_count"] = 0
    assert ([r["name"] for r in repo_facts.select("simonw", PAYLOAD)]
            == [r["name"] for r in repo_facts.select("simonw", zeroed)]
            == ["llm", "datasette", "sqlite-utils", "shot-scraper"])


def test_the_api_order_is_kept_because_the_api_order_is_recency():
    """`sort=updated&direction=desc`. The lane does not re-sort, and re-sorting is the
    only way a magnitude could get in."""
    assert [r["name"] for r in repo_facts.select("simonw", PAYLOAD)] \
        == [r["name"] for r in PAYLOAD]


def test_forks_archived_repos_and_other_peoples_repos_are_dropped():
    payload = [
        _row("mine"),
        _row("a-fork", fork=True),
        _row("old", archived=True),
        _row("theirs", owner="somebodyelse"),
        {"name": "", "full_name": "simonw/", "owner": {"login": "simonw"}},
    ]
    assert [r["name"] for r in repo_facts.select("simonw", payload)] == ["mine"]


def test_ownership_matches_case_insensitively_and_falls_back_to_full_name():
    payload = [_row("one", owner="SimonW"),
               {"name": "two", "full_name": "simonw/two", "pushed_at": ""}]
    assert [r["name"] for r in repo_facts.select("simonw", payload)] == ["one", "two"]


def test_the_cap_holds():
    payload = [_row(f"r{i}") for i in range(20)]
    got = repo_facts.select("simonw", payload)
    assert len(got) == repo_facts.MAX_REPOS_PER_DEV == 6
    assert [r["name"] for r in got] == [f"r{i}" for i in range(6)]


def test_a_payload_that_is_not_a_list_selects_nothing():
    assert repo_facts.select("simonw", {"message": "Not Found"}) == ()
    assert repo_facts.select("simonw", None) == ()


# --- the element shape --------------------------------------------------------

def test_a_fact_carries_exactly_the_frozen_element_fields():
    fact = repo_facts.to_fact(_row("llm", stars=42))
    assert sorted(fact.to_dict()) == sorted(
        ["name", "title", "description", "language", "topics", "stars_fact",
         "first_seen", "last_push"])
    assert fact.stars_fact == 42
    assert fact.last_push == "2026-08-20"


def test_title_is_the_repo_name_because_github_has_no_title():
    """Inventing a prettified title would be generated copy about a named person's
    project. The site defaults `title` to `name` anyway."""
    assert repo_facts.to_fact(_row("shot-scraper")).title == "shot-scraper"


def test_stars_fact_is_the_only_magnitude_and_is_none_when_absent():
    assert repo_facts.to_fact({"name": "x"}).stars_fact is None
    assert repo_facts.to_fact(_row("x", stars=0)).stars_fact == 0
    fields = set(repo_facts.RepoFact.__dataclass_fields__)
    assert not (fields & {"stars", "stargazers_count", "forks_count", "watchers",
                          "followers", "contributions"})


def test_first_seen_is_the_vaults_own_capture_not_githubs_created_at():
    """The field means "when the vault first saw this repo". A page saying otherwise is
    wrong about a fact, so GitHub's `created_at` is never read."""
    fact = repo_facts.to_fact(
        _row("llm", created_at="2015-01-01T00:00:00Z"),
        first_seen_by_repo={"simonw/llm": "2026-03-04T00:00:00+00:00"})
    assert fact.first_seen == "2026-03-04T00:00:00+00:00"
    assert repo_facts.to_fact(_row("llm")).first_seen is None


def test_empty_strings_become_null_rather_than_empty_facts():
    fact = repo_facts.to_fact(_row("x", description="  ", language=None, topics=None))
    assert fact.description is None and fact.language is None and fact.topics == ()


# --- the budget ---------------------------------------------------------------

def test_a_call_is_spent_and_populated_is_true_when_the_call_returns():
    budget = repo_facts.RepoBudget(2)
    client = _Client()
    facts, populated = repo_facts.facts_for("simonw", client, budget=budget)
    assert populated is True and len(facts) == 4
    assert budget.used == 1
    path, params = client.calls[0]
    assert path == "/users/simonw/repos"
    assert params["per_page"] == 100 and params["sort"] == "updated"


def test_an_exhausted_budget_returns_nothing_populated_false_and_makes_no_call():
    """NOBODY LOOKED. The empty list must not be read as "this person owns no repos"."""
    budget = repo_facts.RepoBudget(0)
    client = _Client()
    facts, populated = repo_facts.facts_for("simonw", client, budget=budget)
    assert facts == () and populated is False
    assert client.calls == []


def test_a_raising_client_returns_populated_false_and_does_not_propagate():
    budget = repo_facts.RepoBudget(5)
    facts, populated = repo_facts.facts_for("simonw", _Client(raises=True),
                                            budget=budget)
    assert facts == () and populated is False
    assert budget.used == 1, "a failed call still cost quota and must still be counted"


def test_a_404_returns_populated_false_rather_than_an_empty_repo_card():
    facts, populated = repo_facts.facts_for(
        "gone", _Client(payload=None), budget=repo_facts.RepoBudget(5))
    assert facts == () and populated is False


def test_a_genuinely_empty_page_is_populated_true_because_somebody_did_look():
    """The one empty list that IS a fact about the person, and the reason `populated` is
    returned rather than inferred from `len(facts)`."""
    facts, populated = repo_facts.facts_for(
        "newbie", _Client(payload=[]), budget=repo_facts.RepoBudget(5))
    assert facts == () and populated is True


def test_the_budget_is_a_hard_shared_ceiling_and_never_borrows():
    budget = repo_facts.RepoBudget(2)
    client = _Client()
    for login in ("a", "b", "c", "d"):
        repo_facts.facts_for(login, client, budget=budget)
    assert budget.used == 2 and budget.exhausted is True
    assert len(client.calls) == 2


def test_a_budget_never_reports_more_used_than_its_cap():
    budget = repo_facts.RepoBudget(-5)
    assert budget.cap == 0 and budget.remaining == 0 and budget.take() is False


# --- the boundary --------------------------------------------------------------

def test_the_repo_path_is_on_the_public_read_allowlist():
    """F053. The xyora token carries admin:org and repo scope; every path this lane can
    reach is a deliberate, reviewable entry in one list."""
    assert repo_facts.USER_REPOS_PATH in fanout.PUBLIC_READ_PATHS


def test_the_cache_ttl_is_a_week_and_that_is_the_whole_cost_argument():
    """A 24h TTL would re-buy a 1,300-dev corpus every morning for metadata that changes
    weekly. 168h means a cold run populates the cap, the next two finish the corpus, and
    the steady state is roughly corpus/7 calls a day."""
    assert repo_facts.REPO_CACHE_TTL_HOURS == 168


# --- the budget bounds REST calls, not cache hits ------------------------------

class _CachingClient:
    """A client with the real one's two counters, serving a repeat from cache."""

    def __init__(self):
        self.seen: set[str] = set()
        self._calls = 0
        self._cache_hits = 0

    def request(self, path, params=None):
        if path in self.seen:
            self._cache_hits += 1
        else:
            self.seen.add(path)
            self._calls += 1
        return PAYLOAD


def test_a_cache_hit_gives_the_budget_claim_back():
    """WITHOUT THIS THE CORPUS NEVER FILLS AND EVERY METER STILL READS HEALTHY. A cold
    run buys the cap; the next run would otherwise spend the whole ceiling re-reading the
    same devs out of the 168-hour cache and never reach the rest."""
    client = _CachingClient()
    budget = repo_facts.RepoBudget(2)
    repo_facts.facts_for("simonw", client, budget=budget)
    assert budget.used == 1
    facts, populated = repo_facts.facts_for("simonw", client, budget=budget)
    assert populated is True and facts
    assert budget.used == 1, "the second read was a cache hit and cost no quota"
    assert client._calls == 1 and client._cache_hits == 1


def test_a_second_run_over_a_warm_cache_reaches_devs_the_first_run_could_not():
    """The shape the whole 168-hour TTL argument depends on, asserted end to end."""
    client = _CachingClient()
    everyone = [f"dev{i}" for i in range(6)]

    def a_run(cap):
        budget = repo_facts.RepoBudget(cap)
        return {login for login in everyone
                if repo_facts.facts_for(login, client, budget=budget)[1]}

    first = a_run(3)
    assert first == {"dev0", "dev1", "dev2"}
    second = a_run(3)
    assert second == set(everyone), "the warm three cost nothing, so all six are reached"


def test_a_client_with_no_cache_counter_still_charges_for_every_call():
    """A stub client reports no counters. Refunding on "unknown" would make the ceiling
    unbounded against exactly the clients that cannot prove they cached anything."""
    budget = repo_facts.RepoBudget(5)
    client = _Client()
    for login in ("a", "b", "c"):
        repo_facts.facts_for(login, client, budget=budget)
    assert budget.used == 3


def test_refund_never_goes_below_zero():
    budget = repo_facts.RepoBudget(2)
    budget.refund()
    assert budget.used == 0
