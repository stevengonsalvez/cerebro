from __future__ import annotations

from cerebro.gitintel.cache import GitIntelCache
from cerebro.gitintel.crackscore import cheap_score, deep_score

NOW = "2026-06-30T00:00:00+00:00"
WEEK_AGO = "2026-06-23T00:00:00+00:00"
MONTH_AGO = "2026-05-30T00:00:00+00:00"


class FakeClient:
    """No network. Serves a single user payload, repo list, and events feed."""

    def __init__(self, user=None, repos=None, events=None):
        self._user = user
        self._repos = repos or []
        self._events = events or []

    def get_user(self, login):
        return self._user

    def get_user_repos(self, login, limit=20):
        return self._repos

    def request(self, path, params=None):
        # only used for /users/{login}/events
        return self._events


def _push(created_at, size=3):
    return {"type": "PushEvent", "created_at": created_at, "payload": {"size": size}}


def _seed_follower_growth(cache):
    cache.record_developer_metrics("builder", followers=100, public_repos=20, captured_at=WEEK_AGO)
    cache.record_developer_metrics("builder", followers=60, public_repos=18, captured_at=MONTH_AGO)


def _builder_client(events=None):
    return FakeClient(
        user={
            "login": "builder",
            "html_url": "https://github.com/builder",
            "name": "Real Builder",
            "followers": 320,
            "public_repos": 40,
            "created_at": "2025-01-01T00:00:00Z",
        },
        repos=[
            {"full_name": "builder/hot", "html_url": "u", "pushed_at": NOW},
            {"full_name": "builder/warm", "html_url": "u", "pushed_at": WEEK_AGO},
        ],
        events=events,
    )


def test_cheap_score_combines_three_signals():
    cache = GitIntelCache(":memory:")
    _seed_follower_growth(cache)
    score = cheap_score("builder", _builder_client(), cache, captured_at=NOW)
    assert score.deep is False
    assert score.commits_per_day == 0.0
    assert 0.0 <= score.score <= 1.0
    assert score.followers_gained_30d > 0
    assert score.ships_score > 0


def test_deep_score_shifts_up_for_high_commit_dev():
    cache = GitIntelCache(":memory:")
    _seed_follower_growth(cache)
    base = cheap_score("builder", _builder_client(), cache, captured_at=NOW)
    # heavy shipper: ~4.7 commits/day in window -> commit signal maxes out
    events = [_push("2026-06-%02dT00:00:00Z" % d, size=15) for d in range(1, 29)]
    deep = deep_score(base, _builder_client(events=events), window_days=90, now=NOW)
    assert deep.deep is True
    assert deep.commits_per_day > 0
    assert deep.score > base.score
    assert 0.0 <= deep.score <= 1.0


def test_deep_score_ranks_high_commit_above_low_commit():
    cache = GitIntelCache(":memory:")
    _seed_follower_growth(cache)
    base = cheap_score("builder", _builder_client(), cache, captured_at=NOW)
    heavy = deep_score(
        base,
        _builder_client(events=[_push("2026-06-%02dT00:00:00Z" % d, size=15) for d in range(1, 29)]),
        now=NOW,
    )
    light = deep_score(
        base,
        _builder_client(events=[_push("2026-06-15T00:00:00Z", size=1)]),
        now=NOW,
    )
    assert heavy.score > light.score


def test_zero_history_candidate_no_crash():
    cache = GitIntelCache(":memory:")
    client = FakeClient(user=None, repos=[], events=[])
    base = cheap_score("ghost", client, cache, captured_at=NOW)
    assert base.score == 0.0
    assert base.deep is False
    deep = deep_score(base, client, now=NOW)
    assert deep.deep is True
    assert deep.commits_per_day == 0.0
    assert deep.score == 0.0


def test_non_pushevent_entries_ignored():
    cache = GitIntelCache(":memory:")
    _seed_follower_growth(cache)
    base = cheap_score("builder", _builder_client(), cache, captured_at=NOW)
    noise = [
        {"type": "WatchEvent", "created_at": NOW, "payload": {"size": 99}},
        {"type": "IssuesEvent", "created_at": NOW, "payload": {"commits": [1, 2, 3]}},
    ]
    deep = deep_score(base, _builder_client(events=noise), now=NOW)
    assert deep.commits_per_day == 0.0


def test_commits_outside_window_excluded():
    cache = GitIntelCache(":memory:")
    _seed_follower_growth(cache)
    base = cheap_score("builder", _builder_client(), cache, captured_at=NOW)
    events = [
        _push("2026-06-28T00:00:00Z", size=5),      # inside 90d window
        _push("2020-01-01T00:00:00Z", size=100),    # far outside window
        _push("2026-07-15T00:00:00Z", size=100),    # future, after now
    ]
    deep = deep_score(base, _builder_client(events=events), window_days=90, now=NOW)
    # only the 5-commit in-window push counts
    assert deep.commits_per_day == round(5 / 90, 4)


def test_score_deterministic_and_bounded():
    cache = GitIntelCache(":memory:")
    _seed_follower_growth(cache)
    a = cheap_score("builder", _builder_client(), cache, captured_at=NOW)
    b = cheap_score("builder", _builder_client(), cache, captured_at=NOW)
    assert a.score == b.score
    assert 0.0 <= a.score <= 1.0
