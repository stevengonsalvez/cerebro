"""F057 — the pipeline writes its own history, or the growth it wants can never exist.

The charter's settled fact: `crackscore.py:39,44` passes `record=False`, so the scorer
never wrote the snapshots its own follower/portfolio growth terms read. Those terms are
structurally 0 without a snapshot >=7 days old, the weights sum to 0.50 without them, and
the admission threshold is 0.55 — admission was arithmetically impossible and the pipeline
could not self-heal, because the missing history was the thing it declined to write.

So the two tables here are written unconditionally from the FREE lane, and there is no
flag to turn them off. These tests pin that, pin the one-instant-per-run property the
counting depends on, and pin that opening a pre-e06 cache file migrates it without
touching a row of anything else.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cerebro.gitintel.cache import GitIntelCache


@dataclass(frozen=True)
class _M:
    """A `gharchive.WindowMetrics` stand-in. The writer is duck-typed on purpose: the
    cache is infrastructure UNDER the lane and must not import the lane back."""

    active_days: int = 0
    pushes: int = 0
    distinct_repos: int = 0
    repos_not_owned: int = 0
    not_owned_basenames: int = 0
    not_owned_owners: int = 0


def test_a_window_metric_round_trips_through_both_tables(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    wrote = c.record_window_metrics("SimonW", 30, _M(
        active_days=17, pushes=53, distinct_repos=22, repos_not_owned=4,
        not_owned_basenames=3, not_owned_owners=2), captured_at="2026-08-27T07:00:00+00:00")
    assert wrote == 2

    assert c.active_day_snapshots("simonw", 30) == [
        {"captured_at": "2026-08-27T07:00:00+00:00", "active_days": 17}]
    assert c.push_window_snapshots("simonw", 30) == [{
        "captured_at": "2026-08-27T07:00:00+00:00", "pushes": 53, "distinct_repos": 22,
        "repos_not_owned": 4, "not_owned_basenames": 3, "not_owned_owners": 2}]


def test_logins_are_stored_folded_so_one_person_is_one_history(tmp_path):
    """The pool carries whatever casing the lane that won precedence spelled. Two casings
    of one person must not become two histories with half the days each."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    c.record_window_metrics("Rich-Harris", 90, _M(active_days=9),
                            captured_at="2026-08-20T07:00:00+00:00")
    c.record_window_metrics("rich-harris", 90, _M(active_days=11),
                            captured_at="2026-08-21T07:00:00+00:00")
    got = c.active_day_snapshots("RICH-HARRIS", 90)
    assert [r["active_days"] for r in got] == [9, 11]


def test_rewriting_the_same_instant_replaces_and_never_duplicates(tmp_path):
    """A re-run of the same stage on the same day must not double the history it reads."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    for value in (5, 6, 7):
        c.record_window_metrics("obra", 7, _M(active_days=value, pushes=value),
                                captured_at="2026-08-27T07:00:00+00:00")
    rows = c.active_day_snapshots("obra", 7)
    assert len(rows) == 1 and rows[0]["active_days"] == 7
    assert len(c.push_window_snapshots("obra", 7)) == 1


def test_windows_are_separate_histories(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    for w, days in ((7, 5), (30, 17), (90, 44)):
        c.record_window_metrics("simonw", w, _M(active_days=days),
                                captured_at="2026-08-27T07:00:00+00:00")
    assert c.active_day_snapshots("simonw", 7)[0]["active_days"] == 5
    assert c.active_day_snapshots("simonw", 30)[0]["active_days"] == 17
    assert c.active_day_snapshots("simonw", 90)[0]["active_days"] == 44


def test_history_reads_oldest_first_whatever_order_it_was_written(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    for stamp, days in (("2026-08-27T07:00:00+00:00", 20),
                        ("2026-08-19T07:00:00+00:00", 12),
                        ("2026-08-23T07:00:00+00:00", 16)):
        c.record_window_metrics("simonw", 30, _M(active_days=days), captured_at=stamp)
    got = c.active_day_snapshots("simonw", 30)
    assert [r["captured_at"] for r in got] == sorted(r["captured_at"] for r in got)
    assert [r["active_days"] for r in got] == [12, 16, 20]


def test_an_unknown_login_is_an_empty_history_not_a_raise(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    assert c.active_day_snapshots("nobody", 30) == []
    assert c.push_window_snapshots("nobody", 30) == []


def test_an_empty_login_writes_nothing_and_says_so(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    assert c.record_window_metrics("", 30, _M(active_days=3)) == 0
    assert c.db.execute("SELECT count(*) FROM active_day_snapshots").fetchone()[0] == 0


def test_a_malformed_count_is_zero_and_never_takes_the_run_down(tmp_path):
    """The write happens in the free lane before admission. It is not allowed to raise."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    c.record_window_metrics("x", 30, _M(active_days="not a number", pushes=None),
                            captured_at="2026-08-27T07:00:00+00:00")
    assert c.active_day_snapshots("x", 30)[0]["active_days"] == 0
    assert c.push_window_snapshots("x", 30)[0]["pushes"] == 0


def test_last_snapshot_at_is_none_before_any_history_exists(tmp_path):
    """F058's operator as-of. `None` says "no run has EVER recorded history", which is a
    different and louder statement than an old date."""
    c = GitIntelCache(tmp_path / "c.sqlite")
    assert c.last_snapshot_at() is None


def test_last_snapshot_at_is_the_newest_instant_across_every_login(tmp_path):
    c = GitIntelCache(tmp_path / "c.sqlite")
    c.record_window_metrics("a", 30, _M(pushes=1), captured_at="2026-08-19T07:00:00+00:00")
    c.record_window_metrics("b", 30, _M(pushes=1), captured_at="2026-08-27T07:00:00+00:00")
    c.record_window_metrics("c", 7, _M(pushes=1), captured_at="2026-08-23T07:00:00+00:00")
    assert c.last_snapshot_at() == "2026-08-27T07:00:00+00:00"


def test_a_memory_cache_records_history_that_dies_with_it(tmp_path):
    """The ONLY supported way to run without persisting: no flag, a different store. A
    `record=False` parameter is what produced the defect this feature exists to fix."""
    c = GitIntelCache(":memory:")
    assert c.record_window_metrics("simonw", 30, _M(active_days=17)) == 2
    assert len(c.active_day_snapshots("simonw", 30)) == 1


def test_there_is_no_way_to_ask_the_writer_not_to_record():
    """The charter's settled defect, asserted as a property of the signature."""
    import inspect

    params = inspect.signature(GitIntelCache.record_window_metrics).parameters
    assert "record" not in params
    src = inspect.getsource(GitIntelCache.record_window_metrics)
    assert "record=False" not in src


def test_opening_a_pre_e06_cache_migrates_it_without_touching_a_row(tmp_path):
    """The live cache is 356 MB of `github_responses`. The migration is "open the file",
    and it has to be a no-op for everything already in there."""
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(str(path))
    old.executescript("""
        CREATE TABLE github_responses (
          cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL,
          status_code INTEGER NOT NULL, fetched_at TEXT NOT NULL);
        CREATE TABLE developer_metric_snapshots (
          login TEXT NOT NULL, captured_at TEXT NOT NULL, followers INTEGER NOT NULL,
          public_repos INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(login, captured_at));
    """)
    old.execute("INSERT INTO github_responses VALUES('k','{\"a\": 1}',200,'2026-08-27T07:00:00')")
    old.execute("INSERT INTO developer_metric_snapshots VALUES('simonw','2026-08-21T07:00:00',1,2)")
    old.commit()
    old.close()

    c = GitIntelCache(path)
    tables = {r[0] for r in c.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"active_day_snapshots", "push_window_snapshots"} <= tables
    assert c.db.execute("SELECT count(*) FROM github_responses").fetchone()[0] == 1
    assert c.db.execute(
        "SELECT count(*) FROM developer_metric_snapshots").fetchone()[0] == 1
    assert c.db.execute("SELECT response_json FROM github_responses").fetchone()[0] \
        == '{"a": 1}'
