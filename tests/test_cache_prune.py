"""F064 — the prune policy, and the horizon it is forbidden to eat.

MEASURED, NOT ASSUMED: the unbounded thing here is the RESPONSE CACHE. This worktree's
`cerebro-gitintel.sqlite` was 356 MB after one cold run — 3,409 rows carrying 352 MB of
`response_json` — and `cache.py` had no `DELETE` in it anywhere: `get_response` checks
freshness and returns `None`, leaving the row on disk for ever. A snapshot row is ~60
bytes and the whole 2,568-login pool writes ~7,700 a day.

The dangerous failure mode of a prune is not that it deletes too little. It is that it
deletes the history the growth reader is waiting seven days to be able to read. So the
retention constant is asserted against that horizon, both directions, by arithmetic.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

import pytest

from cerebro.gitintel import cache as cache_mod
from cerebro.gitintel.cache import (
    RESPONSE_RETAIN_HOURS,
    SNAPSHOT_RETAIN_DAILY_DAYS,
    SNAPSHOT_RETAIN_WEEKLY_DAYS,
    GitIntelCache,
)

NOW = dt.datetime(2026, 8, 27, 7, 0, 0, tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class _M:
    active_days: int = 1
    pushes: int = 1
    distinct_repos: int = 1
    repos_not_owned: int = 0
    not_owned_basenames: int = 0
    not_owned_owners: int = 0


def _seed_snapshot(cache, login, days_ago, *, window=90, active_days=1):
    stamp = (NOW - dt.timedelta(days=days_ago)).replace(microsecond=0).isoformat()
    cache.record_window_metrics(login, window, _M(active_days=active_days),
                                captured_at=stamp)
    return stamp


def _seed_response(cache, key, hours_ago):
    """Written in `set_response`'s own convention: NAIVE LOCAL, which is not the
    convention `captured_at` uses. The prune has to know that."""
    stamp = (NOW - dt.timedelta(hours=hours_ago)).astimezone().replace(
        tzinfo=None).isoformat(timespec="seconds")
    cache.db.execute("INSERT OR REPLACE INTO github_responses VALUES(?,?,?,?)",
                     (key, '{"x": 1}', 200, stamp))
    cache.db.commit()


def _count(cache, table):
    return cache.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# --- the constants are a contract with the growth reader ----------------------

def test_daily_retention_covers_the_widest_window_plus_the_growth_lookback():
    """120 = 90-day window + 30-day lookback. The arithmetic, not the literal."""
    assert SNAPSHOT_RETAIN_DAILY_DAYS >= 90 + 30


def test_weekly_retention_is_strictly_beyond_daily_retention():
    """The bands must not overlap or invert, or downsampling would eat live history."""
    assert SNAPSHOT_RETAIN_WEEKLY_DAYS > SNAPSHOT_RETAIN_DAILY_DAYS


def test_response_retention_outlives_every_client_ttl_in_the_lane():
    """A pruned response must be one no live client could have HIT. The longest TTL in
    the lane is the repo lane's 168 h; 336 is twice that."""
    from cerebro.gitintel import repo_facts

    assert RESPONSE_RETAIN_HOURS >= 2 * repo_facts.REPO_CACHE_TTL_HOURS
    assert RESPONSE_RETAIN_HOURS >= 24


# --- github_responses --------------------------------------------------------

def test_a_response_older_than_the_retention_is_deleted_and_a_newer_one_is_not(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    _seed_response(c, "old", RESPONSE_RETAIN_HOURS + 1)
    _seed_response(c, "new", RESPONSE_RETAIN_HOURS - 1)

    out = c.prune(now=NOW)
    assert out["responses_deleted"] == 1
    keys = {r[0] for r in c.db.execute("SELECT cache_key FROM github_responses")}
    assert keys == {"new"}


def test_a_three_thousand_row_response_table_prunes_exactly_the_rows_past_the_cutoff(
        tmp_path):
    """The measured shape: 3,409 rows / 352 MB after one cold run. Half of this fixture
    is past 336 h, and exactly half must go."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    for i in range(1500):
        _seed_response(c, f"old-{i}", RESPONSE_RETAIN_HOURS + 1 + (i % 100))
    for i in range(1500):
        _seed_response(c, f"fresh-{i}", (i % 300))
    assert _count(c, "github_responses") == 3000

    out = c.prune(now=NOW)
    assert out["responses_deleted"] == 1500
    assert _count(c, "github_responses") == 1500
    assert not [r for r in c.db.execute(
        "SELECT cache_key FROM github_responses WHERE cache_key LIKE 'old-%'")]


def test_pruning_an_empty_cache_is_a_no_op_that_still_reports(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    out = c.prune(now=NOW)
    assert out["responses_deleted"] == 0
    assert out["snapshots_deleted"] == 0
    assert out["snapshots_downsampled"] == 0
    assert out["bytes_before"] > 0          # the file exists even when the tables do not


# --- the snapshot bands ------------------------------------------------------

def test_every_row_inside_the_growth_horizon_survives(tmp_path):
    """THE ASSERTION THE WHOLE POLICY EXISTS FOR. Nothing the growth reader can read is
    ever deleted; the condemned scorer's defect was history that did not exist, and a
    prune that ate it would recreate it with extra steps."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    for days in range(0, SNAPSHOT_RETAIN_DAILY_DAYS):
        _seed_snapshot(c, "simonw", days)
    before = _count(c, "active_day_snapshots")

    out = c.prune(now=NOW)
    assert out["snapshots_deleted"] == 0
    assert out["snapshots_downsampled"] == 0
    assert _count(c, "active_day_snapshots") == before


@pytest.mark.parametrize("days_ago", [SNAPSHOT_RETAIN_WEEKLY_DAYS + 1,
                                      SNAPSHOT_RETAIN_WEEKLY_DAYS + 30])
def test_a_row_past_the_weekly_band_is_deleted(tmp_path, days_ago):
    """The boundary is inclusive on the KEEP side throughout: a row exactly
    `SNAPSHOT_RETAIN_WEEKLY_DAYS` old is still retained, one older is not."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    _seed_snapshot(c, "simonw", days_ago)
    out = c.prune(now=NOW)
    assert out["snapshots_deleted"] == 2       # one row in each table
    assert _count(c, "active_day_snapshots") == 0


def test_a_five_hundred_day_history_downsamples_to_one_row_per_login_per_iso_week(
        tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    for days in range(0, 500):
        _seed_snapshot(c, "simonw", days, active_days=days % 90)

    c.prune(now=NOW)

    rows = c.active_day_snapshots("simonw", 90)
    daily_cut = NOW - dt.timedelta(days=SNAPSHOT_RETAIN_DAILY_DAYS)
    weekly_cut = NOW - dt.timedelta(days=SNAPSHOT_RETAIN_WEEKLY_DAYS)
    inside, band, beyond = [], [], []
    for row in rows:
        when = dt.datetime.fromisoformat(row["captured_at"])
        (inside if when >= daily_cut else band if when >= weekly_cut else beyond
         ).append(when)

    assert beyond == [], "a row past the weekly band survived"
    # Inclusive on the keep side: days 0..120 inclusive are daily rows, which is 121.
    assert len(inside) == SNAPSHOT_RETAIN_DAILY_DAYS + 1, \
        "a daily row inside the horizon was eaten"
    weeks = [w.isocalendar()[:2] for w in band]
    assert len(weeks) == len(set(weeks)), "the weekly band kept two rows in one week"
    # Every ISO week that had a row before the prune still has exactly one after.
    expected_weeks = {
        (NOW - dt.timedelta(days=d)).isocalendar()[:2]
        for d in range(SNAPSHOT_RETAIN_DAILY_DAYS + 1, 500)
        if d <= SNAPSHOT_RETAIN_WEEKLY_DAYS}
    assert set(weeks) == expected_weeks


def test_downsampling_keeps_the_newest_row_in_each_week(tmp_path):
    """Newest, so a downsampled history still reads as a series of measurements taken on
    a weekly cadence rather than a mix of stale and fresh ones."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    stamps = [_seed_snapshot(c, "simonw", 200 + offset, active_days=offset)
              for offset in range(0, 7)]
    c.prune(now=NOW)
    kept = c.active_day_snapshots("simonw", 90)
    # One ISO week of daily rows collapses to its newest, which is the smallest days_ago.
    assert len(kept) == 1
    assert kept[0]["captured_at"] == max(stamps)
    assert kept[0]["active_days"] == 0


def test_downsampling_is_per_login_and_per_window(tmp_path):
    """Two people, three windows, one week: six rows in, six rows out."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    for login in ("simonw", "obra"):
        for window in (7, 30, 90):
            for offset in range(0, 5):
                _seed_snapshot(c, login, 200 + offset, window=window)
    c.prune(now=NOW)
    for login in ("simonw", "obra"):
        for window in (7, 30, 90):
            assert len(c.active_day_snapshots(login, window)) == 1, (login, window)


def test_an_unparseable_captured_at_is_left_alone_rather_than_swept(tmp_path):
    """A row the prune cannot read is not evidence that nothing else can."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    c.db.execute("INSERT INTO active_day_snapshots VALUES('x',90,'not-a-date',3)")
    c.db.commit()
    c.prune(now=NOW)
    assert _count(c, "active_day_snapshots") == 1


def test_the_prune_never_vacuums_and_reports_the_freelist_instead(tmp_path):
    """A 356 MB file rewrite inside a 07:00 stage is a new outage mode. The operator
    reclaims out of band; the stage only says how much there is to reclaim."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(GitIntelCache.prune)))
    executed = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    body = tree.body[0]
    docstring = ast.get_docstring(body, clean=False) or ""
    for literal in executed:
        if literal == docstring:
            continue
        assert "VACUUM" not in literal.upper(), literal

    c = GitIntelCache(tmp_path / "c.sqlite")
    for i in range(200):
        _seed_response(c, f"old-{i}", RESPONSE_RETAIN_HOURS + 5)
    out = c.prune(now=NOW)
    assert out["responses_deleted"] == 200
    assert out["freelist_pages"] >= 0
    assert out["bytes_before"] > 0
    # The FILE has not shrunk: the pages are free, not returned to the filesystem.
    assert c.path.stat().st_size >= out["bytes_before"]


def test_the_prune_reports_bytes_before_from_the_real_file(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    _seed_response(c, "k", 1)
    out = c.prune(now=NOW)
    assert out["bytes_before"] == c.path.stat().st_size


def test_a_memory_cache_prunes_and_reports_zero_bytes():
    c = GitIntelCache(":memory:")
    assert c.prune(now=NOW)["bytes_before"] == 0


def test_the_prune_does_not_touch_the_other_tables(tmp_path):
    """Only three policies exist. `repo_inspections`, `profile_inspections`, `search_runs`
    and the pre-e06 metric snapshots are out of scope and must stay untouched."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    c.db.execute("INSERT INTO repo_inspections VALUES('a/b','{}','2020-01-01T00:00:00')")
    c.db.execute("INSERT INTO profile_inspections VALUES('x','{}','2020-01-01T00:00:00')")
    c.db.execute("INSERT INTO search_runs VALUES('r','q','{}','{}','2020-01-01T00:00:00')")
    c.record_developer_metrics("simonw", followers=1, captured_at="2020-01-01T00:00:00")
    c.db.commit()

    c.prune(now=NOW)

    for table in ("repo_inspections", "profile_inspections", "search_runs",
                  "developer_metric_snapshots"):
        assert _count(c, table) == 1, table


def test_the_response_cutoff_is_built_in_the_columns_own_time_convention():
    """`fetched_at` is naive local; `captured_at` is aware UTC. Comparing one against the
    other silently deletes or spares up to a timezone's worth of rows."""
    import inspect

    src = inspect.getsource(GitIntelCache.prune)
    assert "_as_naive_local" in src and "_iso_utc" in src


def test_the_helper_agrees_with_sqlite_on_row_counts(tmp_path):
    """The reported numbers are the rows that actually left the database."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    for days in range(0, 500):
        _seed_snapshot(c, "simonw", days)
    before = _count(c, "active_day_snapshots") + _count(c, "push_window_snapshots")
    out = c.prune(now=NOW)
    after = _count(c, "active_day_snapshots") + _count(c, "push_window_snapshots")
    assert before - after == out["snapshots_deleted"] + out["snapshots_downsampled"]


def test_the_tables_the_policy_operates_on_are_declared():
    assert cache_mod.SNAPSHOT_TABLES == ("active_day_snapshots", "push_window_snapshots")


def test_pruning_twice_is_idempotent(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    for days in range(0, 500):
        _seed_snapshot(c, "simonw", days)
    c.prune(now=NOW)
    second = c.prune(now=NOW)
    assert second["snapshots_deleted"] == 0
    assert second["snapshots_downsampled"] == 0


def test_the_schema_survives_a_prune(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    c.prune(now=NOW)
    tables = {r[0] for r in c.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"github_responses", *cache_mod.SNAPSHOT_TABLES} <= tables
    assert isinstance(sqlite3.connect(str(c.path)), sqlite3.Connection)
