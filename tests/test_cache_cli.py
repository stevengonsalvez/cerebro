"""F064b — the prune is wired into the stage, and the cache is inspectable.

Two properties that are easy to get wrong in opposite directions:

  1. the cleanup runs LAST and cannot lose the run's work. A prune that raises must leave
     every artifact on disk and the stage exiting normally.
  2. the numbers reach the budget artifact. A retention policy nobody can see the effect
     of is indistinguishable from one nobody wired up — the same class as the consent
     gate's `optout_removed` counter.

`cache-vacuum` is a separate, operator-run command precisely because it is the expensive
half: rewriting a 375 MB file inside the 07:00 stage is a new outage mode invented to
solve a disk-space problem.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cerebro import config
from cerebro.__main__ import main
from cerebro.gitintel import devs_spike
from cerebro.gitintel.cache import GitIntelCache

from test_devs_history import CachedClient, CachelessClient, _run
from test_devs_spike import HUMANS


def _budget(paths):
    return json.loads(paths["budget"].read_text(encoding="utf-8"))


def test_the_stage_prunes_and_records_what_it_deleted(tmp_path):
    cache_path = tmp_path / "gitintel.sqlite"
    cache = GitIntelCache(cache_path)
    for i in range(40):
        cache.db.execute(
            "INSERT INTO github_responses VALUES(?,?,?,?)",
            (f"stale-{i}", "{}", 200, "2020-01-01T00:00:00"))
    cache.db.commit()

    (_r, _t, _rec, paths), logged = _run(tmp_path, CachedClient(HUMANS, cache))
    budget = _budget(paths)
    assert budget["responses_deleted"] == 40
    assert budget["cache_bytes"] > 0
    assert cache.db.execute(
        "SELECT count(*) FROM github_responses").fetchone()[0] == 0
    assert any("cache prune:" in line for line in logged), logged


def test_a_fresh_response_is_not_pruned_by_the_stage(tmp_path):
    """The negative control. A prune that deletes everything would report the same
    `responses_deleted > 0` as a correct one."""
    import datetime as dt

    cache_path = tmp_path / "gitintel.sqlite"
    cache = GitIntelCache(cache_path)
    cache.db.execute(
        "INSERT INTO github_responses VALUES(?,?,?,?)",
        ("fresh", "{}", 200, dt.datetime.now().isoformat(timespec="seconds")))
    cache.db.commit()

    (_r, _t, _rec, paths), _log = _run(tmp_path, CachedClient(HUMANS, cache))
    assert _budget(paths)["responses_deleted"] == 0
    assert cache.db.execute(
        "SELECT count(*) FROM github_responses").fetchone()[0] == 1


def test_a_prune_that_raises_never_loses_the_runs_work(tmp_path, monkeypatch):
    """THE ORDERING IS THE POINT. Artifacts first, cleanup last, exceptions swallowed
    with a warning: a disk-space chore must never take down a run that has already done
    everything it was for."""
    cache_path = tmp_path / "gitintel.sqlite"
    cache = GitIntelCache(cache_path)

    def explode(*a, **k):
        raise sqlite_error()

    def sqlite_error():
        import sqlite3
        return sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(GitIntelCache, "prune", explode)
    (result, _t, records, paths), logged = _run(tmp_path, CachedClient(HUMANS, cache))

    assert result.ok and records
    for key in ("top", "queue", "json", "census", "budget"):
        assert paths[key].is_file()
    assert _budget(paths)["responses_deleted"] == 0
    assert any("cache prune failed" in line for line in logged), logged


def test_a_cacheless_client_prunes_nothing_and_does_not_raise(tmp_path):
    (result, _t, _rec, paths), _log = _run(tmp_path, CachelessClient(HUMANS))
    assert result.ok
    assert _budget(paths)["cache_bytes"] == 0


def test_the_prune_runs_after_every_artifact_is_written():
    """Asserted on the source, because the ordering is the guarantee."""
    import inspect

    body = inspect.getsource(devs_spike.run)
    assert body.index("census_path.write_text") < body.index("_prune_cache(")
    assert body.index("json_path.write_text") < body.index("_prune_cache(")


# --- the two read-only commands ------------------------------------------------

def _cli(monkeypatch, tmp_path, capsys, *argv):
    settings = type("S", (), {"vault_path": tmp_path, "dry_run": True, "sources": {},
                              "github": {"cache_path": str(tmp_path / "c.sqlite")},
                              "ntfy_topic": ""})()
    monkeypatch.setattr(config, "load", lambda **kw: settings)
    import cerebro.__main__ as main_mod
    monkeypatch.setattr(main_mod, "load", lambda **kw: settings, raising=False)
    old = sys.argv
    sys.argv = ["cerebro", *argv]
    try:
        main()
    finally:
        sys.argv = old
    text = capsys.readouterr().out
    return json.loads(text[text.index("{"):])


def test_cache_stats_reports_rows_bytes_and_the_snapshot_span(
        tmp_path, monkeypatch, capsys):
    cache = GitIntelCache(tmp_path / "c.sqlite")
    cache.record_window_metrics("simonw", 90, type("M", (), {"active_days": 3})(),
                                captured_at="2026-08-20T07:00:00+00:00")
    cache.record_window_metrics("simonw", 90, type("M", (), {"active_days": 5})(),
                                captured_at="2026-08-27T07:00:00+00:00")
    cache.db.execute("INSERT INTO github_responses VALUES('k','{\"a\": 1}',200,'2026-08-27T07:00:00')")
    cache.db.commit()

    out = _cli(monkeypatch, tmp_path, capsys, "cache-stats")
    assert out["tables"]["push_window_snapshots"]["rows"] == 2
    assert out["tables"]["github_responses"]["payload_bytes"] > 0
    assert out["snapshots"]["history_days"] == 7.0
    assert out["snapshots"]["logins"] == 1 and out["snapshots"]["instants"] == 2
    assert out["file_bytes"] > 0


def test_cache_stats_on_an_empty_cache_says_zero_history_rather_than_failing(
        tmp_path, monkeypatch, capsys):
    """`history_days: 0.0` with `instants: 0` is the honest reading of a cache that has
    never recorded anything, and it is what an operator needs to see before waiting seven
    days for a growth number that can never arrive."""
    GitIntelCache(tmp_path / "c.sqlite")
    out = _cli(monkeypatch, tmp_path, capsys, "cache-stats")
    assert out["snapshots"] == {"oldest": None, "newest": None, "logins": 0,
                                "instants": 0, "history_days": 0.0}


def test_cache_vacuum_reports_before_and_after_and_actually_shrinks_the_file(
        tmp_path, monkeypatch, capsys):
    cache = GitIntelCache(tmp_path / "c.sqlite")
    for i in range(400):
        cache.db.execute("INSERT INTO github_responses VALUES(?,?,?,?)",
                         (f"k{i}", "x" * 4000, 200, "2020-01-01T00:00:00"))
    cache.db.commit()
    cache.prune()
    cache.close()

    out = _cli(monkeypatch, tmp_path, capsys, "cache-vacuum")
    assert out["bytes_before"] > out["bytes_after"] > 0
    assert out["bytes_freed"] == out["bytes_before"] - out["bytes_after"]


def test_the_cache_commands_never_reach_the_orchestrator(tmp_path, monkeypatch, capsys):
    """Structurally incapable of triggering a pipeline run, like every other devs-lane
    subcommand: they return before the orchestrator is even imported."""
    import cerebro.__main__ as main_mod

    def explode(*a, **k):
        raise AssertionError("the orchestrator was imported by a cache command")

    monkeypatch.setattr("cerebro.orchestrator.run", explode, raising=False)
    GitIntelCache(tmp_path / "c.sqlite")
    assert _cli(monkeypatch, tmp_path, capsys, "cache-stats")["file_bytes"] >= 0
    assert main_mod is not None


@pytest.mark.parametrize("field", ["responses_deleted", "snapshots_deleted",
                                   "snapshots_downsampled", "cache_bytes"])
def test_the_budget_declares_the_prune_meters(field):
    from cerebro.gitintel.pool import Budget
    assert field in Budget().to_dict()
