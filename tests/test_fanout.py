"""T04t — F003/F063 the contributor fan-out lane. No network.

The two properties that matter here are both about what does NOT survive the call.
GitHub hands this lane a commit count on every contributor and returns the page in
commit-count order, so the lane is the exact place a volume signal could enter the pool.
It cannot, for two independent reasons, and both are asserted: the count has no field to
land in, and the ordering is destroyed before the caller sees it.
"""
from __future__ import annotations

import dataclasses

from cerebro.gitintel import fanout
from cerebro.gitintel.fanout import FanoutCandidate, contributors, fanout_lane, work_queue
from cerebro.gitintel.vault_seed import SeedRepo


class FakeClient:
    """Records every path requested. `payloads` is keyed by full_name."""

    def __init__(self, payloads, fail=()):
        self.payloads = payloads
        self.fail = set(fail)
        self.paths: list[str] = []
        self.params: list[dict] = []

    def request(self, path, params=None):
        self.paths.append(path)
        self.params.append(params or {})
        full = path[len("/repos/"):-len("/contributors")]
        if full in self.fail:
            raise RuntimeError("boom")
        return self.payloads.get(full)


def _c(login, type_="User", contributions=999):
    """A contributors-payload row shaped exactly like GitHub's, commit count included —
    the tests must feed the field in so its absence downstream means something."""
    return {"login": login, "type": type_, "contributions": contributions,
            "followers_url": f"https://api.github.com/users/{login}/followers"}


def _seed(owner, name, hashes):
    return SeedRepo(owner=owner, name=name, signal_hashes=tuple(hashes), first_seen="")


# --- the volume ordering dies at the boundary (F020, F063) ------------------

def test_the_api_commit_count_order_is_destroyed_and_the_result_is_alphabetical():
    """MEASURED SHAPE: simonw/llm came back 1170, 10, 5, 5, 4 — the page IS the volume
    ranking. This fixture is deliberately in that order and must come back alphabetical,
    so no downstream consumer can read position as quality."""
    payload = [_c("zed", contributions=1170), _c("Mallory", contributions=10),
               _c("alice", contributions=5), _c("bob", contributions=4)]
    cl = FakeClient({"simonw/llm": payload})
    got = contributors("simonw/llm", cl)
    assert got == ("alice", "bob", "Mallory", "zed")
    assert got != tuple(r["login"] for r in payload)


def test_the_candidate_dataclass_has_no_field_a_commit_count_could_land_in():
    """The leak check inspects the DATACLASS, which is where a leak could actually
    occur. A `hasattr(login_string, "contributions")` probe over the returned logins is
    False for every conceivable implementation, including a broken one, and validates
    nothing."""
    banned = {"contributions", "followers", "stars", "stargazers_count",
              "contribution_count", "score", "rank"}
    fields = {f.name for f in dataclasses.fields(FanoutCandidate)}
    assert fields == {"login", "via_repos", "signal_hashes"}
    assert not (fields & banned)


def test_the_lane_returns_logins_not_payload_rows():
    """A tuple of strings cannot carry a commit count no matter what the caller does."""
    cl = FakeClient({"a/b": [_c("alice")]})
    got = contributors("a/b", cl)
    assert all(isinstance(x, str) for x in got)


# --- the free rejects, off the payload's own fields (F011, §3.3) ------------

def test_a_bot_type_is_rejected_inline_at_zero_extra_rest_cost():
    """`github-actions[bot]` is `type: Bot` in the contributors payload itself, so the
    expensive get_user pre-filter never has to see it."""
    cl = FakeClient({"a/b": [_c("github-actions[bot]", type_="Bot"), _c("alice")]})
    assert contributors("a/b", cl) == ("alice",)


def test_a_bot_suffix_is_rejected_even_when_the_type_says_user():
    cl = FakeClient({"a/b": [_c("dependabot[bot]", type_="User"), _c("alice")]})
    assert contributors("a/b", cl) == ("alice",)


def test_an_organization_type_is_rejected():
    cl = FakeClient({"a/b": [_c("someorg", type_="Organization"), _c("alice")]})
    assert contributors("a/b", cl) == ("alice",)


def test_a_vendor_org_login_is_rejected():
    cl = FakeClient({"a/b": [_c("google"), _c("anthropic"), _c("alice")]})
    assert contributors("a/b", cl) == ("alice",)


def test_a_blank_or_missing_login_is_skipped_not_emitted_as_empty():
    cl = FakeClient({"a/b": [{"type": "User"}, _c("   ", ), _c("alice")]})
    assert contributors("a/b", cl) == ("alice",)


# --- cost shape: one page, one call (F003, F053) ---------------------------

def test_exactly_one_rest_call_per_repo_on_page_one_only():
    cl = FakeClient({"a/b": [_c("alice")]})
    contributors("a/b", cl)
    assert cl.paths == ["/repos/a/b/contributors"]
    assert cl.params == [{"per_page": 100}]
    assert "page" not in cl.params[0], "walking pages is out of scope and out of budget"


def test_the_lane_spends_one_call_per_repo_and_no_more():
    seeds = [_seed("a", "b", ["h1"]), _seed("c", "d", ["h2"]), _seed("e", "f", ["h3"])]
    cl = FakeClient({"a/b": [_c("alice")], "c/d": [_c("bob")], "e/f": [_c("alice")]})
    cands, repos_read = fanout_lane(seeds, cl, limit=10)
    assert len(cl.paths) == 3 == repos_read
    assert {c.login for c in cands} == {"alice", "bob"}


# --- one dead repo must not sink the lane (the _resolve_owners precedent) ---

def test_a_raising_repo_returns_empty_and_the_lane_continues():
    seeds = [_seed("a", "b", ["h1"]), _seed("c", "d", ["h2"])]
    cl = FakeClient({"c/d": [_c("bob")]}, fail={"a/b"})
    cands, _ = fanout_lane(seeds, cl, limit=10)
    assert [c.login for c in cands] == ["bob"]


def test_a_404_returning_none_is_empty_not_a_crash():
    cl = FakeClient({"a/b": None})
    assert contributors("a/b", cl) == ()


def test_a_non_list_payload_is_empty_not_a_crash():
    cl = FakeClient({"a/b": {"message": "Repository access blocked"}})
    assert contributors("a/b", cl) == ()


# --- F063: the work queue orders REPOS, never people ------------------------

def test_the_work_queue_is_in_signal_recurrence_order():
    """The corpus's real recurrers go first: claude-code 36 notes, codex 8, llm 4. A
    truncated run spends its calls where the vault keeps returning, not alphabetically."""
    seeds = [
        _seed("zzz", "singleton", ["h1"]),
        _seed("anthropics", "claude-code", [f"h{i}" for i in range(36)]),
        _seed("simonw", "llm", [f"g{i}" for i in range(4)]),
        _seed("openai", "codex", [f"f{i}" for i in range(8)]),
    ]
    got = [s.full_name for s in work_queue(seeds, limit=10)]
    assert got == ["anthropics/claude-code", "openai/codex", "simonw/llm", "zzz/singleton"]


def test_the_work_queue_breaks_ties_on_the_key_so_the_run_is_byte_stable():
    seeds = [_seed("b", "r", ["h"]), _seed("A", "r", ["h"]), _seed("c", "r", ["h"])]
    assert [s.owner for s in work_queue(seeds, limit=10)] == ["A", "b", "c"]


def test_the_work_queue_truncates_to_the_limit():
    seeds = [_seed(f"o{i}", "r", ["h"]) for i in range(50)]
    assert len(work_queue(seeds, limit=7)) == 7
    assert work_queue(seeds, limit=0) == []


def test_the_recurrence_count_the_queue_sorts_on_enters_no_candidate_field():
    """F063's whole licence is that recurrence orders WORK and never a person. The count
    must therefore be unreachable from the lane's output."""
    seeds = [_seed("a", "b", [f"h{i}" for i in range(36)])]
    cl = FakeClient({"a/b": [_c("alice")]})
    cands, _ = fanout_lane(seeds, cl, limit=1)
    flat = dataclasses.asdict(cands[0])
    assert "recurrence" not in str(flat)
    assert set(flat) == {"login", "via_repos", "signal_hashes"}


# --- provenance is a union, and the hop is exactly one ---------------------

def test_a_person_found_on_three_repos_arrives_once_with_all_three():
    seeds = [_seed("a", "b", ["h1"]), _seed("c", "d", ["h2"]), _seed("e", "f", ["h3"])]
    cl = FakeClient({"a/b": [_c("alice")], "c/d": [_c("alice")], "e/f": [_c("alice")]})
    cands, _ = fanout_lane(seeds, cl, limit=10)
    assert len(cands) == 1
    assert cands[0].via_repos == ("a/b", "c/d", "e/f")
    assert cands[0].signal_hashes == ("h1", "h2", "h3")


def test_signal_hashes_are_inherited_through_exactly_one_hop():
    """A fan-out candidate is in the pool because of a REPO. The hashes are the repo's,
    which is what lets the profile copy say the hop honestly instead of implying the
    person was personally cited."""
    seeds = [_seed("a", "b", ["note-1", "note-2"])]
    cl = FakeClient({"a/b": [_c("alice")]})
    cands, _ = fanout_lane(seeds, cl, limit=1)
    assert cands[0].signal_hashes == ("note-1", "note-2")


def test_the_lane_output_is_key_sorted_so_the_artifact_diffs_cleanly():
    seeds = [_seed("a", "b", ["h"])]
    cl = FakeClient({"a/b": [_c("Zoe"), _c("alice"), _c("Bob")]})
    cands, _ = fanout_lane(seeds, cl, limit=1)
    assert [c.login for c in cands] == ["alice", "Bob", "Zoe"]


def test_the_public_read_allowlist_names_the_path_this_module_calls():
    assert fanout.CONTRIBUTORS_PATH.format(full_name="o/r") == "/repos/o/r/contributors"
    assert "/repos/{owner}/{repo}/contributors" in fanout.PUBLIC_READ_PATHS
