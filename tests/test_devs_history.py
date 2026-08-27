"""F057 — the run writes its own history, and the meter is checked against the store.

The charter's settled defect: crackscan could never self-heal because it never recorded
the history its own scoring read. So the assertion that matters is not "a function was
called" but "rows appeared in the database, and the number the budget reports is the
number the database actually holds". A budget checked against itself is how a run reports
`healthy: true` while measuring nothing.

The second half is the cache-less case. A client with no `.cache` is a legitimate
configuration (a stub, a hand-rolled double), it records nothing, and the run must SAY SO
rather than print a silent 0 — the e03 failure, restated.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from cerebro.gitintel import devs_spike
from cerebro.gitintel.cache import GitIntelCache

from test_devs_spike import FIXTURE, HUMANS, _corpus, _transport, _verdicts


class CachedClient:
    """A `GitHubClient` stand-in that carries the one attribute F057 reads: `.cache`."""

    def __init__(self, logins, cache):
        self.logins = {x.lower(): x for x in logins}
        self.cache = cache
        self._calls = 0
        self._cache_hits = 0
        self._errors = 0

    def get_user(self, login):
        self._calls += 1
        real = self.logins.get((login or "").lower())
        return None if not real else {"login": real, "type": "User", "name": real,
                                      "public_repos": 5}

    def request(self, path, params=None):
        self._calls += 1
        return []


class CachelessClient(CachedClient):
    """The stub shape. `.cache` is absent, not None — both must be handled."""

    def __init__(self, logins):
        super().__init__(logins, cache=None)
        del self.cache


def _run(tmp_path, client, out="out"):
    vault = _corpus(tmp_path, HUMANS)
    logged: list[str] = []
    result = devs_spike.run(
        vault, tmp_path / out, client=client,
        verdicts_path=_verdicts(tmp_path), limit=20,
        log=logged.append, transport=_transport())
    return result, logged


def _counts(path):
    db = sqlite3.connect(str(path))
    try:
        return {
            "active": db.execute("SELECT count(*) FROM active_day_snapshots").fetchone()[0],
            "push": db.execute("SELECT count(*) FROM push_window_snapshots").fetchone()[0],
            "instants": db.execute(
                "SELECT count(DISTINCT captured_at) FROM push_window_snapshots").fetchone()[0],
            "logins": db.execute(
                "SELECT count(DISTINCT login) FROM push_window_snapshots").fetchone()[0],
        }
    finally:
        db.close()


def test_a_run_writes_one_row_per_login_per_window_in_each_table(tmp_path):
    cache_path = tmp_path / "gitintel.sqlite"
    client = CachedClient(HUMANS, GitIntelCache(cache_path))
    (_result, _top, records, _paths), _log = _run(tmp_path, client)

    expected = len(records) * len(devs_spike.WINDOWS)
    got = _counts(cache_path)
    assert got["active"] == expected
    assert got["push"] == expected
    assert got["logins"] == len(records)


def test_the_budget_number_equals_the_rows_the_database_actually_holds(tmp_path):
    """THE METER IS CHECKED AGAINST THE STORE, NOT AGAINST ITSELF."""
    import json

    cache_path = tmp_path / "gitintel.sqlite"
    client = CachedClient(HUMANS, GitIntelCache(cache_path))
    (_r, _t, _rec, paths), _log = _run(tmp_path, client)

    budget = json.loads(paths["budget"].read_text(encoding="utf-8"))
    assert budget["snapshots_written"] == _counts(cache_path)["active"]
    assert budget["snapshots_written"] == _counts(cache_path)["push"]
    assert budget["snapshot_store"] == str(cache_path)


def test_one_run_is_exactly_one_instant_across_the_whole_pool(tmp_path):
    """`count(distinct captured_at)` has to answer "how many runs are in here". A
    per-login clock would put a 2,568-login run's rows either side of a second."""
    cache_path = tmp_path / "gitintel.sqlite"
    _run(tmp_path, CachedClient(HUMANS, GitIntelCache(cache_path)))
    assert _counts(cache_path)["instants"] == 1


def test_a_second_run_a_simulated_day_later_accrues_without_disturbing_the_first(
        tmp_path, monkeypatch):
    """THE >=7-DAY GROWTH CLOCK, PROVEN TO TICK. Two runs a simulated day apart leave two
    instants and twice the rows; the first day's numbers are still exactly what they were.
    """
    cache_path = tmp_path / "gitintel.sqlite"
    day1 = dt.datetime(2026, 8, 20, 7, 0, 0, tzinfo=dt.timezone.utc)

    monkeypatch.setattr(devs_spike, "_now_utc", lambda: day1)
    _run(tmp_path, CachedClient(HUMANS, GitIntelCache(cache_path)), out="out1")
    first = GitIntelCache(cache_path).active_day_snapshots("simonw", 90)
    assert len(first) == 1

    monkeypatch.setattr(devs_spike, "_now_utc",
                        lambda: day1 + dt.timedelta(days=1))
    (_r, _t, records, _p), _log = _run(
        tmp_path, CachedClient(HUMANS, GitIntelCache(cache_path)), out="out2")

    got = _counts(cache_path)
    assert got["instants"] == 2
    assert got["active"] == len(records) * len(devs_spike.WINDOWS) * 2
    after = GitIntelCache(cache_path).active_day_snapshots("simonw", 90)
    assert after[0] == first[0], "the first day's history was disturbed by the second run"
    assert after[0]["captured_at"] == "2026-08-20T07:00:00+00:00"
    assert after[1]["captured_at"] == "2026-08-21T07:00:00+00:00"


def test_history_is_written_before_admission_can_refuse_anybody(tmp_path):
    """MEASUREMENT IS NOT A REWARD FOR PUBLISHING. Every login the free scan covered gets
    a row, including the ones admission holds back, so a run whose gate fails still
    advances the growth clock."""
    cache_path = tmp_path / "gitintel.sqlite"
    client = CachedClient(HUMANS, GitIntelCache(cache_path))
    (_r, _t, records, _p), _log = _run(tmp_path, client)

    withheld = [r for r in records if not r.admitted]
    cache = GitIntelCache(cache_path)
    for rec in records:
        assert cache.active_day_snapshots(rec.login, 90), rec.login
    # The fixture cohort admits everybody; the assertion above is the general one, and
    # this line records which case the fixture actually exercised.
    assert isinstance(withheld, list)


def test_the_source_orders_the_snapshot_write_before_the_paid_prefilter():
    """The ordering is the feature, so it is asserted on the source rather than inferred
    from a run that happens to admit everybody."""
    src = devs_spike.run.__doc__ or ""
    assert src  # the docstring exists; the real assertion is the ordering below
    import inspect
    body = inspect.getsource(devs_spike.run)
    assert body.index("_record_history(") < body.index("pool.paid_prefilter(")
    assert body.index("gharchive.pool_metrics(") < body.index("_record_history(")


def test_a_cacheless_client_records_nothing_and_announces_that_it_did(tmp_path):
    """AN UNMEASURED METER SAYS SO. The exact e03 failure otherwise: a silent 0."""
    import json

    (_r, _t, _rec, paths), logged = _run(tmp_path, CachelessClient(HUMANS))
    budget = json.loads(paths["budget"].read_text(encoding="utf-8"))
    assert budget["snapshots_written"] == 0
    assert budget["snapshot_store"] == ""
    assert any("the client has no cache" in line for line in logged), logged


def test_the_cacheless_run_still_exits_normally(tmp_path):
    """Recording no history is a degraded MEASUREMENT, not a failed run."""
    (result, _top, records, _paths), _log = _run(tmp_path, CachelessClient(HUMANS))
    assert result.ok
    assert records


def test_a_memory_cache_is_how_a_caller_declines_to_persist(tmp_path):
    """There is no `record=False`; the store is the knob. The rows exist for the life of
    the process and no file is touched."""
    client = CachedClient(HUMANS, GitIntelCache(":memory:"))
    (_r, _t, records, paths), _log = _run(tmp_path, client)
    import json
    budget = json.loads(paths["budget"].read_text(encoding="utf-8"))
    assert budget["snapshots_written"] == len(records) * len(devs_spike.WINDOWS)
    assert budget["snapshot_store"] == ":memory:"


def test_the_recorded_numbers_are_the_ones_the_free_scan_returned(tmp_path):
    """Recomputed independently from the fixture TSV, not read back from the module that
    wrote them."""
    cache_path = tmp_path / "gitintel.sqlite"
    _run(tmp_path, CachedClient(HUMANS, GitIntelCache(cache_path)))

    header, *rows = FIXTURE.read_text(encoding="utf-8").splitlines()
    cols = header.split("\t")
    wanted = {}
    for line in rows:
        if not line.strip():
            continue
        cells = dict(zip(cols, line.split("\t")))
        wanted[cells["actor_login"].lower()] = (int(cells["active_days"]),
                                                int(cells["pushes"]))

    cache = GitIntelCache(cache_path)
    checked = 0
    for login, (active_days, pushes) in wanted.items():
        got_active = cache.active_day_snapshots(login, 90)
        if not got_active:
            continue                      # not in this test's pool
        assert got_active[0]["active_days"] == active_days
        assert cache.push_window_snapshots(login, 90)[0]["pushes"] == pushes
        checked += 1
    assert checked > 1, "the fixture recomputation checked nothing"


@pytest.mark.parametrize("field", ["snapshots_written", "snapshot_store"])
def test_the_budget_declares_the_history_meter(field):
    from cerebro.gitintel.pool import Budget
    assert field in Budget().to_dict()


class LockedCache(GitIntelCache):
    """A cache whose snapshot table is unavailable, the way a concurrent VACUUM leaves it.

    `cerebro cache-vacuum` takes a long exclusive lock over a 384MB file. An operator who
    runs it across the 07:00 stage gets exactly this: every `record_window_metrics` raises
    `sqlite3.OperationalError: database is locked`.
    """

    def record_window_metrics(self, login, window_days, metrics, *, captured_at=None):
        raise sqlite3.OperationalError("database is locked")


class HalfLockedCache(GitIntelCache):
    """Fails every write after the first, so `pairs` has to be a count and not a total."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._seen = 0

    def record_window_metrics(self, login, window_days, metrics, *, captured_at=None):
        self._seen += 1
        if self._seen > 1:
            raise sqlite3.OperationalError("database is locked")
        return super().record_window_metrics(login, window_days, metrics,
                                             captured_at=captured_at)


def test_a_locked_snapshot_store_degrades_the_run_instead_of_killing_it(tmp_path):
    """`cache.py` claims the snapshot write "must never be the thing that takes a run down".

    Nothing enforced that claim until now. The write is not one of the two GHArchive
    exception types `__main__` catches, so a locked database raised straight out through
    `_record_history` and killed the whole refresh with a traceback BEFORE any corpus was
    written. The corpus was never at risk — `run.sh` contained it — but the operator was
    paged for a crash when the truth was a degraded run, and a wrong diagnosis at 07:00 is
    its own kind of damage.
    """
    client = CachedClient(HUMANS, LockedCache(str(tmp_path / "locked.sqlite3")))
    (result, _top, records, _paths), logged = _run(tmp_path, client)
    assert result.ok, "a locked snapshot store must not fail the run"
    assert records, "the corpus is written even when no history could be recorded"


def test_the_locked_store_announces_the_failure_rather_than_reporting_a_clean_zero(tmp_path):
    """COUNTED, NOT SWALLOWED — the e03 lesson applied one layer down.

    A bare `except: pass` here would rebuild the exact hole that let e03 print
    `healthy: true` through 273 rate-limit errors: a meter reading zero because nothing
    was measured, indistinguishable from a meter reading zero because nothing was wrong.
    """
    import json

    client = CachedClient(HUMANS, LockedCache(str(tmp_path / "locked.sqlite3")))
    (_r, _t, _rec, paths), logged = _run(tmp_path, client)
    budget = json.loads(paths["budget"].read_text(encoding="utf-8"))
    assert budget["snapshots_written"] == 0, "no row landed, so the meter must say 0"
    assert any("snapshot write failed" in line for line in logged), logged
    assert any("snapshot write(s) failed this run" in line for line in logged), logged


def test_the_written_count_counts_rows_that_landed_not_writes_attempted(tmp_path):
    """`budget.snapshots_written` stays checkable against a live sqlite3 count.

    With one write succeeding and the rest raising, a total-based counter would report the
    attempted number and the budget would once again be checked against itself.
    """
    import json

    cache = HalfLockedCache(str(tmp_path / "half.sqlite3"))
    client = CachedClient(HUMANS, cache)
    (_r, _t, _rec, paths), _log = _run(tmp_path, client)
    budget = json.loads(paths["budget"].read_text(encoding="utf-8"))
    rows = cache.db.execute("SELECT COUNT(*) FROM active_day_snapshots").fetchone()[0]
    assert budget["snapshots_written"] == 1
    assert rows == 1, "exactly the one write that was allowed through"
