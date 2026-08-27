"""T03b — the REST call counter, pinned. No network.

WHY THIS FILE EXISTS AT ALL. Before e02, `GitHubClient` had no counter: `request()`
incremented nothing, and `devs_spike.py` read `getattr(client, "_calls", 0)` twice. Every
"N REST calls" this repo has ever printed was therefore a structural zero — a budget
report that passes whatever the lane actually spent. The counter is the prerequisite for
every budget claim in e02, so its semantics are pinned here rather than left to reading.

Two rules, and the split between them is load-bearing:
  · `_calls` counts what LEAVES THE PROCESS, incremented before `requests.get`. A 404
    and a transport exception both count: both spent quota.
  · `_cache_hits` counts the early return. A CACHE HIT IS NOT A REST CALL — without the
    split, "a second run inside 24h is materially cheaper" is unmeasurable.
"""
from __future__ import annotations

import pytest
import requests

from cerebro.gitintel.github_client import GitHubClient, GitHubClientError


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.headers = {}
        self.text = ""

    def json(self):
        return self._payload


def _client(tmp_path, monkeypatch, responses):
    """A client with a real on-disk cache and a fake transport. `responses` is popped
    per call; an Exception instance is raised instead of returned."""
    calls: list[tuple] = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params))
        r = responses.pop(0) if len(responses) > 1 else responses[0]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(requests, "get", fake_get)

    class _S:
        github = {"cache_path": str(tmp_path / "cache.sqlite"), "cache_ttl_hours": 24}

    cl = GitHubClient(_S(), token="")
    cl._transport_calls = calls
    return cl


def test_a_fresh_client_starts_at_zero_on_both_counters(tmp_path, monkeypatch):
    cl = _client(tmp_path, monkeypatch, [_Resp(200, {"login": "x"})])
    assert cl._calls == 0
    assert cl._cache_hits == 0


def test_the_counters_are_real_attributes_not_a_getattr_default(tmp_path, monkeypatch):
    """The guard every budget assertion opens with. `getattr(client, "_calls", 0)`
    against an uninstrumented client returns 0 and passes a budget check vacuously, so
    the attributes must genuinely exist."""
    cl = _client(tmp_path, monkeypatch, [_Resp(200, {})])
    assert hasattr(cl, "_calls") and hasattr(cl, "_cache_hits")
    assert "_calls" in vars(cl) and "_cache_hits" in vars(cl)


def test_a_cache_miss_increments_calls_only(tmp_path, monkeypatch):
    cl = _client(tmp_path, monkeypatch, [_Resp(200, {"login": "simonw"})])
    assert cl.request("/users/simonw") == {"login": "simonw"}
    assert cl._calls == 1
    assert cl._cache_hits == 0


def test_a_cache_hit_increments_cache_hits_only_and_is_not_a_rest_call(tmp_path, monkeypatch):
    """The whole point of the split. Re-reading the same path inside the TTL must move
    `_cache_hits` and leave `_calls` where it was, or the 24h cache cannot be shown to
    make the Court-settled daily refresh cadence affordable."""
    cl = _client(tmp_path, monkeypatch, [_Resp(200, {"login": "simonw"})])
    cl.request("/users/simonw")
    assert (cl._calls, cl._cache_hits) == (1, 0)
    cl.request("/users/simonw")
    assert (cl._calls, cl._cache_hits) == (1, 1)
    assert len(cl._transport_calls) == 1, "the second read must not leave the process"


def test_a_404_still_counts_as_a_call_because_it_cost_quota(tmp_path, monkeypatch):
    cl = _client(tmp_path, monkeypatch, [_Resp(404, {"message": "Not Found"})])
    assert cl.request("/repos/nobody/nothing") is None
    assert cl._calls == 1
    assert cl._cache_hits == 0


def test_a_transport_exception_still_counts_as_a_call(tmp_path, monkeypatch):
    """Counted BEFORE the call precisely so this case is not lost. A run that burns its
    budget on failures must report a spent budget, not a clean one."""
    cl = _client(tmp_path, monkeypatch, [requests.ConnectionError("reset by peer")])
    with pytest.raises(GitHubClientError):
        cl.request("/users/simonw")
    assert cl._calls == 1
    assert cl._cache_hits == 0


def test_a_4xx_that_raises_still_counts(tmp_path, monkeypatch):
    cl = _client(tmp_path, monkeypatch, [_Resp(403, {"message": "rate limited"})])
    with pytest.raises(GitHubClientError):
        cl.request("/users/simonw")
    assert cl._calls == 1


# --- the third counter: calls that RAISED --------------------------------------
#
# `_calls` says what left the process and `_errors` says how much of it came back
# broken. The split is what lets `devs-refresh` tell a DEGRADED run from a small one:
# every REST consumer in the devs lane swallows its own exceptions on purpose, so
# without a counter at the client a rate-limited run resolves nobody and reports a
# clean bill of health. See `tests/test_devs_degraded.py`.

def test_a_fresh_client_starts_at_zero_errors(tmp_path, monkeypatch):
    cl = _client(tmp_path, monkeypatch, [_Resp(200, {})])
    assert cl._errors == 0
    assert "_errors" in vars(cl), "a getattr default would report a healthy run vacuously"


def test_a_403_increments_errors(tmp_path, monkeypatch):
    """The measured production case: `GitHub 403 ... API rate limit exceeded`."""
    cl = _client(tmp_path, monkeypatch, [_Resp(403, {"message": "API rate limit exceeded"})])
    with pytest.raises(GitHubClientError):
        cl.request("/users/simonw")
    assert (cl._calls, cl._errors) == (1, 1)


def test_a_transport_exception_increments_errors(tmp_path, monkeypatch):
    cl = _client(tmp_path, monkeypatch, [requests.ConnectionError("reset by peer")])
    with pytest.raises(GitHubClientError):
        cl.request("/users/simonw")
    assert (cl._calls, cl._errors) == (1, 1)


def test_a_404_is_an_answer_and_not_an_error(tmp_path, monkeypatch):
    """A 404 for `/users/{login}` MEANS the account is gone, and a run that met one
    deleted account is not degraded. A health predicate that cried wolf on this would be
    turned off, which is worse than not having one."""
    cl = _client(tmp_path, monkeypatch, [_Resp(404, {"message": "Not Found"})])
    assert cl.request("/users/ghost") is None
    assert (cl._calls, cl._errors) == (1, 0)


def test_a_success_never_increments_errors(tmp_path, monkeypatch):
    cl = _client(tmp_path, monkeypatch, [_Resp(200, {"login": "simonw"})])
    cl.request("/users/simonw")
    cl.request("/users/simonw")           # cache hit
    assert cl._errors == 0


def test_distinct_paths_do_not_share_a_cache_entry(tmp_path, monkeypatch):
    cl = _client(tmp_path, monkeypatch,
                 [_Resp(200, {"login": "a"}), _Resp(200, {"login": "b"})])
    cl.request("/users/a")
    cl.request("/users/b")
    assert (cl._calls, cl._cache_hits) == (2, 0)


def test_a_non_2xx_cache_entry_is_retried_and_counted_again(tmp_path, monkeypatch):
    """The cache stores the 404 body but the read path only short-circuits on 2xx, so a
    repeat is a real call and must be counted as one."""
    cl = _client(tmp_path, monkeypatch, [_Resp(404, {"message": "Not Found"})])
    cl.request("/repos/nobody/nothing")
    cl.request("/repos/nobody/nothing")
    assert cl._calls == 2
    assert cl._cache_hits == 0


def test_the_counters_are_a_delta_source_not_a_run_total(tmp_path, monkeypatch):
    """Budget accounting reads (end - start), never the absolute value, because one
    client is shared across lanes. This pins that the counter is monotonic so a delta is
    meaningful."""
    cl = _client(tmp_path, monkeypatch, [_Resp(200, {"n": 1}), _Resp(200, {"n": 2})])
    start = cl._calls
    cl.request("/users/a")
    cl.request("/users/b")
    assert cl._calls - start == 2
