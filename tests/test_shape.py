"""T07t — F014 shape metrics, table-driven from the LIVE calibration cohort.

Every expected value below was measured against play.clickhouse.com on 2026-08-26 at a
90-day window. The table is the executable form of the calibration record.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from cerebro.gitintel import shape
from cerebro.gitintel.gharchive import WindowMetrics, _parse_tsv

FIXTURE = Path(__file__).parent / "fixtures" / "gharchive_cohort_90d.tsv"
COHORT = _parse_tsv(FIXTURE.read_text(encoding="utf-8"), 90)

# login, concentration, push/active-day, not-owned ratio
LIVE_90D = [
    ("Dicklesworthstone", 0.0092, 308.49, 0.0000),
    ("diegosouzapw",      0.9538,  26.14, 0.9538),
    ("koala73",           1.0000,  11.85, 0.9583),
    ("esengine",          0.7273,   9.93, 0.6364),
    ("can1357",           0.7368,   6.17, 0.7368),
    ("santifer",          0.8182,   6.42, 0.8409),
    ("obra",              0.0204,   6.21, 0.7551),
    ("simonw",            0.0556,   4.68, 0.2407),
    ("sindresorhus",      0.0392,   7.14, 0.1569),
    ("t3dotgg",           1.0000,   3.90, 1.0000),
    ("Rich-Harris",       0.5385,   5.25, 0.9231),
    ("kentcdodds",        0.0233,   3.78, 0.7442),
    ("ljharb",            0.1077,   3.31, 0.6308),
    ("paulmillr",         0.0357,   3.22, 0.0000),
    ("mattpocock",        0.1111,   3.48, 0.2222),
]


@pytest.mark.parametrize("login,conc,ppd,ratio", LIVE_90D)
def test_reproduces_the_live_calibration_row(login, conc, ppd, ratio):
    m = COHORT[login]
    assert shape.basename_concentration(m) == pytest.approx(conc, abs=0.02)
    assert shape.push_per_active_day(m) == pytest.approx(ppd, abs=0.02)
    assert shape.not_owned_ratio(m) == pytest.approx(ratio, abs=0.02)


def test_the_five_previously_unmeasured_humans_are_rows_not_a_footnote():
    measured = {login for login, *_ in LIVE_90D}
    assert {"Rich-Harris", "paulmillr", "mattpocock", "kentcdodds", "ljharb"} <= measured


def test_the_human_concentration_band_spans_obra_to_rich_harris():
    """Bottom 0.0204, TOP 0.5385 — not simonw's 0.0556, which earlier notes wrongly
    called the ceiling."""
    lo = shape.basename_concentration(COHORT["obra"])
    hi = shape.basename_concentration(COHORT["Rich-Harris"])
    assert lo == pytest.approx(0.0204, abs=0.02)
    assert hi == pytest.approx(0.5385, abs=0.02)
    assert hi > shape.basename_concentration(COHORT["simonw"])


def test_concentration_is_over_all_repos_not_only_not_owned_ones():
    """Only this definition reproduces every published registry figure. obra has 37
    not-owned repos in 37 basenames: a not-owned-only definition would give 1/37, not
    the published 0.0204 = 1/49."""
    m = COHORT["obra"]
    assert shape.basename_concentration(m) == pytest.approx(
        m.max_basename_group / m.distinct_repos)
    assert shape.basename_concentration(m) != pytest.approx(
        m.max_basename_group / m.repos_not_owned)


def test_zero_denominators_return_zero_never_nan_and_never_raise():
    m = WindowMetrics(window_days=90)
    for fn in (shape.push_per_active_day, shape.repo_per_active_day,
               shape.not_owned_ratio, shape.basename_concentration,
               shape.pushes_per_repo):
        got = fn(m)
        assert got == 0.0
        assert not math.isnan(got)


def test_every_metric_is_a_finite_non_negative_float():
    for m in COHORT.values():
        for fn in (shape.push_per_active_day, shape.repo_per_active_day,
                   shape.not_owned_ratio, shape.basename_concentration,
                   shape.pushes_per_repo):
            got = fn(m)
            assert isinstance(got, float) and math.isfinite(got) and got >= 0.0


def test_repo_per_active_day_is_recorded_for_the_whole_cohort():
    """F014 mandates all three shape metrics be RECORDED, not only the flagging ones."""
    for login, m in COHORT.items():
        assert shape.repo_per_active_day(m) >= 0.0
    assert shape.repo_per_active_day(COHORT["Dicklesworthstone"]) == pytest.approx(
        109 / 90, abs=0.02)


def test_shape_module_does_no_io():
    import inspect
    src = inspect.getsource(shape)
    for forbidden in ("import requests", "urllib", "open(", "Path(", "http"):
        assert forbidden not in src, f"shape must stay pure arithmetic: {forbidden}"
