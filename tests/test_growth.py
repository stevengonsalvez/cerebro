"""F024 — growth is a delta of active days, or it is `None`. It is never 0.

THE DEFECT THIS FILE PINS IS ARITHMETIC, NOT STYLE. `metrics.py:118-138` returns `0.0`
when no snapshot old enough to compare against exists. In the condemned scorer two of the
four weighted terms were therefore 0 on every cold cache, the reachable maximum was 0.50,
and the admission threshold was 0.55 — nobody could ever be admitted, and no test caught
it because every admit test overrode the threshold to 0.02.

A number meaning "we could not measure this" must never be spendable as a number meaning
"this person did not do anything". So: `None`, and an artifact that says how many days of
history are missing.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from cerebro.gitintel import growth
from cerebro.gitintel.cache import GitIntelCache

NOW = dt.datetime(2026, 8, 27, 7, 0, 0, tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class _M:
    active_days: int = 0
    pushes: int = 0
    distinct_repos: int = 0
    repos_not_owned: int = 0
    not_owned_basenames: int = 0
    not_owned_owners: int = 0


def _store(tmp_path, series, login="simonw", window=30):
    """`series` is `[(days_ago, active_days), ...]`, written as real snapshot rows."""
    cache = GitIntelCache(tmp_path / "c.sqlite")
    for days_ago, active in series:
        cache.record_window_metrics(
            login, window, _M(active_days=active),
            captured_at=(NOW - dt.timedelta(days=days_ago)).isoformat())
    return cache


# --- the insufficient-history case, which is the common one on day one --------

def test_no_history_at_all_is_none(tmp_path):
    assert growth.delta(_store(tmp_path, []), "simonw", 30, now=NOW) is None


@pytest.mark.parametrize("days", [0, 1, 3, 6])
def test_history_shorter_than_seven_days_is_none_never_zero(tmp_path, days):
    """SIX DAYS OF HISTORY IS NOT A DELTA OF ZERO."""
    series = [(d, 10 + d) for d in range(days + 1)]
    store = _store(tmp_path, series)
    assert growth.delta(store, "simonw", 30, now=NOW) is None
    entry = growth.describe(store, "simonw", 30, now=NOW)
    assert entry["delta"] is None
    assert entry["delta"] is not 0  # noqa: F632 — identity is the point being asserted
    assert "insufficient history" in entry["reason"]
    assert "of 7 days" in entry["reason"]


def test_the_reason_names_the_day_count_it_actually_has(tmp_path):
    store = _store(tmp_path, [(4, 12), (0, 15)])
    assert growth.describe(store, "simonw", 30, now=NOW)["reason"] == \
        "insufficient history: 4 of 7 days"


def test_the_insufficient_shape_serialises_as_json_null(tmp_path):
    """`grep -c '"delta": 0'` over the artifact must be 0 on a first run."""
    payload = growth.report(_store(tmp_path, [(1, 5), (0, 5)]), ["simonw"], 30, now=NOW)
    text = json.dumps(payload)
    assert '"delta": null' in text
    assert '"delta": 0' not in text


# --- a real delta, recomputed by hand -----------------------------------------

def test_an_eight_day_history_returns_the_exact_arithmetic_delta(tmp_path):
    """RECOMPUTED IN THE TEST FROM THE SEEDED ROWS, not read back from the module."""
    series = [(8, 11), (7, 12), (3, 16), (0, 19)]
    store = _store(tmp_path, series)
    got = growth.delta(store, "simonw", 30, now=NOW)

    baseline_active = 12          # the newest row at or before NOW - 7 days
    latest_active = 19
    assert got is not None
    assert got.active_days_then == baseline_active
    assert got.active_days_now == latest_active
    assert got.delta == latest_active - baseline_active == 7
    assert got.baseline_captured_at == (NOW - dt.timedelta(days=7)).isoformat()
    assert got.history_days == 7.0


def test_the_baseline_is_the_freshest_row_still_old_enough(tmp_path):
    """A baseline from the oldest row would make the delta grow simply because the cache
    is old. The freshest legitimate baseline is the honest comparison."""
    store = _store(tmp_path, [(40, 1), (20, 2), (8, 3), (0, 9)])
    got = growth.delta(store, "simonw", 30, now=NOW)
    assert got.active_days_then == 3
    assert got.baseline_captured_at == (NOW - dt.timedelta(days=8)).isoformat()


def test_a_negative_delta_survives_untouched(tmp_path):
    """People ship less some months. That is a fact about a month, not a judgement about
    a person, and clamping it at zero would be a lie in the flattering direction."""
    store = _store(tmp_path, [(9, 21), (0, 12)])
    got = growth.delta(store, "simonw", 30, now=NOW)
    assert got.delta == -9


def test_a_delta_of_zero_from_real_history_is_a_real_zero(tmp_path):
    """The one legitimate 0: two measurements that are genuinely equal. It is
    distinguishable from the missing case because it is not `None`."""
    store = _store(tmp_path, [(9, 14), (0, 14)])
    got = growth.delta(store, "simonw", 30, now=NOW)
    assert got is not None and got.delta == 0
    assert growth.describe(store, "simonw", 30, now=NOW)["delta"] == 0


def test_the_delta_carries_its_baseline_date(tmp_path):
    """A delta with no as-of date is unfalsifiable: a reader cannot tell a month of
    change from a day of it."""
    payload = growth.describe(_store(tmp_path, [(10, 4), (0, 9)]), "simonw", 30, now=NOW)
    assert payload["baseline_captured_at"] == (NOW - dt.timedelta(days=10)).isoformat()
    assert payload["history_days"] == 10.0


def test_windows_are_separate_histories(tmp_path):
    cache = GitIntelCache(tmp_path / "c.sqlite")
    for window, then, now_days in ((30, 5, 9), (90, 40, 41)):
        cache.record_window_metrics(
            "simonw", window, _M(active_days=then),
            captured_at=(NOW - dt.timedelta(days=9)).isoformat())
        cache.record_window_metrics(
            "simonw", window, _M(active_days=now_days), captured_at=NOW.isoformat())
    assert growth.delta(cache, "simonw", 30, now=NOW).delta == 4
    assert growth.delta(cache, "simonw", 90, now=NOW).delta == 1


def test_logins_are_matched_case_insensitively(tmp_path):
    store = _store(tmp_path, [(9, 2), (0, 6)], login="Rich-Harris")
    assert growth.delta(store, "rich-harris", 30, now=NOW).delta == 4


# --- the report ---------------------------------------------------------------

def test_the_report_answers_for_every_login_including_the_unmeasurable(tmp_path):
    store = _store(tmp_path, [(9, 3), (0, 8)])
    payload = growth.report(store, ["simonw", "nobody"], 30, now=NOW)
    assert set(payload) == {"simonw", "nobody"}
    assert payload["simonw"]["delta"] == 5
    assert payload["nobody"]["delta"] is None


def test_the_census_line_is_honest_on_day_one(tmp_path):
    store = _store(tmp_path, [(0, 3)])
    payload = growth.report(store, ["simonw", "obra"], 30, now=NOW)
    line = growth.census_line(payload)
    assert line.startswith("growth: 0 of 2 logins")
    assert "never 0" in line


def test_the_census_line_counts_the_ready_ones(tmp_path):
    cache = GitIntelCache(tmp_path / "c.sqlite")
    for login in ("simonw", "obra"):
        for days_ago, active in ((9, 2), (0, 5)):
            cache.record_window_metrics(
                login, 30, _M(active_days=active),
                captured_at=(NOW - dt.timedelta(days=days_ago)).isoformat())
    payload = growth.report(cache, ["simonw", "obra", "nobody"], 30, now=NOW)
    assert growth.census_line(payload).startswith("growth: 2 of 3 logins")


def test_a_malformed_captured_at_is_not_a_baseline(tmp_path):
    cache = GitIntelCache(tmp_path / "c.sqlite")
    cache.db.execute("INSERT INTO active_day_snapshots VALUES('simonw',30,'nonsense',4)")
    cache.db.commit()
    cache.record_window_metrics("simonw", 30, _M(active_days=9),
                                captured_at=NOW.isoformat())
    assert growth.delta(cache, "simonw", 30, now=NOW) is None


# --- the rulings, as properties of the code -----------------------------------

def test_growth_never_imports_the_condemned_metrics_module():
    tree = ast.parse(Path("cerebro/gitintel/growth.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").lstrip("."))
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    assert not (imported & {"metrics", "crackscore", "rank"})


def test_admission_does_not_import_growth():
    """A growth term inside an admission floor is the composite coming back. The floors
    are independent empirical predicates and none of them may ask a trend question."""
    tree = ast.parse(Path("cerebro/gitintel/admission.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = {(node.module or "").lstrip(".")} | {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            names = {a.name.split(".")[0] for a in node.names}
        else:
            continue
        assert "growth" not in names, f"admission imports growth: {names}"


def test_the_module_declares_no_weight_no_momentum_and_no_acceleration():
    src = Path("cerebro/gitintel/growth.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            low = node.id.lower()
            assert "score" not in low and "momentum" not in low
            assert "weight" not in low and "accel" not in low
    # No float literal is multiplied by anything: that shape IS a weighted term.
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for side in (node.left, node.right):
                assert not (isinstance(side, ast.Constant)
                            and isinstance(side.value, float)), ast.unparse(node)


def test_the_retention_policy_cannot_shrink_below_what_growth_reads():
    """A BUILD FAILURE, NOT A COMMENT. If the prune's daily band ever fell below the
    growth lookback, the reader would silently lose the rows it is waiting to compare
    against — the condemned defect, recreated with extra steps."""
    from cerebro.gitintel import cache as cache_mod

    assert cache_mod.SNAPSHOT_RETAIN_DAILY_DAYS >= growth.LOOKBACK_DAYS
    assert cache_mod.SNAPSHOT_RETAIN_DAILY_DAYS >= growth.MIN_HISTORY_DAYS
    assert cache_mod.SNAPSHOT_RETAIN_DAILY_DAYS >= 90 + growth.LOOKBACK_DAYS


def test_the_minimum_history_is_the_courts_seven_days():
    assert growth.MIN_HISTORY_DAYS == 7
