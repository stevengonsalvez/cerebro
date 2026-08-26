"""T05t — F006/F018/F019/F022 GH Archive client. No network.

FIXTURE PROVENANCE, stated because the file mixes two measurement dates on purpose.
`gharchive_cohort_90d.tsv` carries e01's live 2026-08-26 90d snapshot for the eight
columns e01 already had — those numbers are the CALIBRATION RECORD the admission
constants were derived from (sindresorhus 7.14, Rich-Harris 0.5385, mvanhorn 8.84) and
re-querying them a day later silently moves the evidence under the Court's rulings.
e02's three new columns (`not_owned_owners`, `dominant_base`, `dominant_repos`) were
measured live on 2026-08-27 against the same 24 logins and spliced in beside them,
because they cannot be derived from the old row. New columns, new date; the pinned
calibration values are untouched, which is the property that matters.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cerebro.gitintel import gharchive
from cerebro.gitintel.gharchive import (
    QUOTA_BUDGET,
    WEEK_SLOTS,
    GHArchiveUnavailable,
    densify_weeks,
    parse_repo_array,
    pool_metrics,
    render_sql,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gharchive_cohort_90d.tsv"

# The real 2026-08-26 21:10:07 UTC quota body, verbatim.
QUOTA_BODY = (
    "Code: 201. DB::Exception: Quota for user `play` for 3600s has been exceeded: "
    "read_rows = 300013713128/300000000000. Interval will end at 2026-08-26 21:11:08. "
    "Name of quota template: `explorer`. (QUOTA_EXPIRED)\n"
)


class FakeTransport:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.sent: list[str] = []

    def __call__(self, sql):
        self.sent.append(sql)
        body = self.bodies.pop(0) if len(self.bodies) > 1 else self.bodies[0]
        if isinstance(body, Exception):
            raise body
        return body


def _fixture_body() -> str:
    return FIXTURE.read_text(encoding="utf-8")


# --- query shape ------------------------------------------------------------

def test_exactly_one_post_per_window():
    t = FakeTransport([_fixture_body()])
    pool_metrics(["simonw", "obra"], transport=t, sleep=lambda s: None)
    assert len(t.sent) == 3   # correctness property: the shared hourly quota is finite


def test_each_window_carries_its_own_interval():
    t = FakeTransport([_fixture_body()])
    pool_metrics(["simonw"], transport=t, sleep=lambda s: None)
    intervals = [s for s in t.sent]
    assert "INTERVAL 7 DAY" in intervals[0]
    assert "INTERVAL 30 DAY" in intervals[1]
    assert "INTERVAL 90 DAY" in intervals[2]


def test_no_placeholder_survives_rendering():
    sql = render_sql(["simonw", "obra"], 90)
    assert "{window}" not in sql and "{logins}" not in sql
    assert "'simonw', 'obra'" in sql


def test_login_quoting_is_injection_safe():
    sql = render_sql(["o'brien", "a\\b"], 7)
    assert "'o\\'brien'" in sql
    assert "'a\\\\b'" in sql
    # nothing that could terminate the IN-list early
    assert sql.count("IN (") == 1


def test_render_sql_is_a_single_scan():
    sql = render_sql(["x"], 90)
    assert sql.count("FROM github_events") == 1
    assert " JOIN " not in sql.upper()


# --- parsing ----------------------------------------------------------------

def test_parses_the_real_cohort_tsv():
    t = FakeTransport([_fixture_body()])
    got = pool_metrics(["simonw", "diegosouzapw"], transport=t, sleep=lambda s: None)
    m = got["simonw"][90]
    assert (m.pushes, m.distinct_repos, m.active_days) == (309, 54, 66)
    assert (m.repos_not_owned, m.not_owned_basenames, m.max_basename_group) == (13, 12, 3)
    d = got["diegosouzapw"][90]
    assert (d.pushes, d.distinct_repos, d.repos_not_owned, d.max_basename_group) == \
        (2274, 130, 124, 124)


def test_absent_login_is_zero_activity_never_a_keyerror():
    t = FakeTransport([_fixture_body()])
    got = pool_metrics(["simonw", "nobody-pushed-here"], transport=t, sleep=lambda s: None)
    m = got["nobody-pushed-here"][90]
    assert m.pushes == 0 and m.active_days == 0 and m.distinct_repos == 0
    assert m.pushes_per_week == (0,) * WEEK_SLOTS


def test_active_days_never_exceeds_the_window():
    """F022 carry-in. The fixture holds the real Dicklesworthstone row at 91 active
    days in a 90-day window — the exact recorded off-by-one, clamped not accepted."""
    raw = _fixture_body()
    assert "\t91\t" in raw, "fixture must still contain the 91-day boundary row"
    t = FakeTransport([raw])
    got = pool_metrics(["Dicklesworthstone"], transport=t, sleep=lambda s: None)
    for window, m in got["Dicklesworthstone"].items():
        assert m.active_days <= window


def test_clamp_applies_to_a_thirty_day_window():
    header = ("actor_login\tpushes\tdistinct_repos\tactive_days\trepos_not_owned\t"
              "not_owned_basenames\tnot_owned_owners\tmax_basename_group\t"
              "dominant_base\tdominant_repos\tweeks_map\n")
    body = header + "someone\t100\t3\t31\t0\t0\t0\t1\tfoo\t[]\t([0],[1])\n"
    t = FakeTransport([body])
    got = pool_metrics(["someone"], windows=(30,), transport=t, sleep=lambda s: None)
    assert got["someone"][30].active_days == 30


def test_result_login_case_folds_onto_the_requested_login():
    header = ("actor_login\tpushes\tdistinct_repos\tactive_days\trepos_not_owned\t"
              "not_owned_basenames\tnot_owned_owners\tmax_basename_group\t"
              "dominant_base\tdominant_repos\tweeks_map\n")
    t = FakeTransport([header + "SimonW\t5\t1\t2\t0\t0\t0\t1\tllm\t[]\t([0],[5])\n"])
    got = pool_metrics(["simonw"], windows=(90,), transport=t, sleep=lambda s: None)
    assert got["simonw"][90].pushes == 5


# --- the weekly series (SCHEMA FREEZE field) --------------------------------

def test_densify_the_real_sparse_t3dotgg_row():
    """Live-measured sparse row: keys 8, 11 and 12 absent, key 0 = current week."""
    got = densify_weeks("([0,1,2,3,4,5,6,7,9,10],[8,9,41,26,40,15,4,11,1,1])")
    assert len(got) == WEEK_SLOTS
    assert got == (0, 0, 1, 1, 0, 11, 4, 15, 40, 26, 41, 9, 8)
    assert got[-1] == 8      # oldest -> newest: the current partial week is last
    assert got[3] == 1       # week key 9 landed at index 12-9 = 3


def test_densify_a_dense_row_round_trips():
    got = densify_weeks("([0,1,2,3,4,5,6,7,8,9,10,11,12],[1,2,3,4,5,6,7,8,9,10,11,12,13])")
    assert got == (13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)


def test_densify_empty_and_garbage_are_all_zero():
    assert densify_weeks("") == (0,) * WEEK_SLOTS
    assert densify_weeks("([],[])") == (0,) * WEEK_SLOTS


def test_weekly_series_only_populated_on_the_ninety_day_window():
    t = FakeTransport([_fixture_body()])
    got = pool_metrics(["simonw"], transport=t, sleep=lambda s: None)
    assert got["simonw"][7].pushes_per_week == (0,) * WEEK_SLOTS
    assert got["simonw"][30].pushes_per_week == (0,) * WEEK_SLOTS
    assert sum(got["simonw"][90].pushes_per_week) > 0


def test_weekly_series_never_exceeds_the_push_total():
    t = FakeTransport([_fixture_body()])
    got = pool_metrics(["simonw", "obra", "Rich-Harris"], transport=t, sleep=lambda s: None)
    for login in ("simonw", "obra", "Rich-Harris"):
        m = got[login][90]
        assert len(m.pushes_per_week) == WEEK_SLOTS
        assert all(isinstance(v, int) for v in m.pushes_per_week)
        assert sum(m.pushes_per_week) <= m.pushes


# --- quota handling ---------------------------------------------------------

def test_quota_waits_for_the_announced_reset_not_a_fixed_backoff():
    """The real 21:10:07 body announces a 21:11:08 reset. The client must sleep to
    21:11:53 (reset + 45s jitter) = 106s, not 60s. A retry measured at 21:11:00 was
    still blocked; one at 21:11:46 succeeded."""
    slept: list[float] = []
    clock = datetime(2026, 8, 26, 21, 10, 7, tzinfo=timezone.utc)
    t = FakeTransport([QUOTA_BODY, _fixture_body()])
    got = pool_metrics(["simonw"], windows=(90,), transport=t,
                       sleep=slept.append, now=lambda: clock)
    assert slept == [106.0]                     # 21:10:07 -> 21:11:53
    assert got["simonw"][90].pushes == 309      # and the retry succeeded
    assert len(t.sent) == 2


def test_unparseable_quota_body_falls_back_to_the_next_top_of_hour():
    slept: list[float] = []
    clock = datetime(2026, 8, 26, 21, 10, 0, tzinfo=timezone.utc)
    body = "Code: 201. DB::Exception: Quota for user `play` for 3600s has been exceeded.\n"
    t = FakeTransport([body, _fixture_body()])
    pool_metrics(["simonw"], windows=(90,), transport=t, sleep=slept.append,
                 now=lambda: clock)
    assert slept == [3045.0]                    # 50 min to 22:00:00, plus 45s jitter


def test_quota_forever_raises_after_exactly_two_windows():
    slept: list[float] = []
    clock = datetime(2026, 8, 26, 21, 10, 7, tzinfo=timezone.utc)
    t = FakeTransport([QUOTA_BODY])
    with pytest.raises(GHArchiveUnavailable):
        pool_metrics(["simonw"], windows=(90,), transport=t, sleep=slept.append,
                     now=lambda: clock)
    assert len(slept) == QUOTA_BUDGET == 2
    assert len(t.sent) == 3     # initial + one per waited window, then give up


def test_a_stale_reset_timestamp_still_sleeps_at_least_the_jitter():
    slept: list[float] = []
    clock = datetime(2026, 8, 26, 23, 0, 0, tzinfo=timezone.utc)   # long past the reset
    t = FakeTransport([QUOTA_BODY, _fixture_body()])
    pool_metrics(["simonw"], windows=(90,), transport=t, sleep=slept.append,
                 now=lambda: clock)
    assert slept == [float(gharchive.QUOTA_JITTER_S)]


# --- transport failures are a different shape -------------------------------

def test_transport_exception_uses_the_short_ladder_then_succeeds():
    slept: list[float] = []
    t = FakeTransport([OSError("connection reset"), _fixture_body()])
    got = pool_metrics(["simonw"], windows=(90,), transport=t, sleep=slept.append)
    assert slept == [30]
    assert got["simonw"][90].pushes == 309


def test_transport_exception_forever_raises_typed():
    t = FakeTransport([OSError("down")])
    with pytest.raises(GHArchiveUnavailable):
        pool_metrics(["simonw"], windows=(90,), transport=t, sleep=lambda s: None)


def test_non_quota_db_exception_uses_the_short_ladder():
    slept: list[float] = []
    err = "Code: 184. DB::Exception: Aggregate function ... ILLEGAL_AGGREGATION\n"
    t = FakeTransport([err])
    with pytest.raises(GHArchiveUnavailable):
        pool_metrics(["simonw"], windows=(90,), transport=t, sleep=slept.append)
    assert slept == [30, 60, 120]


def test_empty_login_list_makes_no_request():
    t = FakeTransport([_fixture_body()])
    assert pool_metrics([], transport=t) == {}
    assert t.sent == []


# --- T02: parse_repo_array, the ClickHouse Array(String) literal ------------
#
# TOTAL, NEVER RAISING. Every failure mode below returns `()`, and `()` means "no fork
# evidence", which the T10 lane treats as fail-closed: the flag stands. A parser that
# raised here would turn a malformed cell into a crashed run; one that guessed would
# turn it into a clearance nobody reviewed.

def test_parses_a_thirty_element_array_whole():
    lit = "[" + ",".join(f"'own{i}/repo'" for i in range(30)) + "]"
    got = parse_repo_array(lit)
    assert len(got) == 30
    assert got[0] == "own0/repo" and got[29] == "own29/repo"


def test_parses_an_empty_array_and_a_blank_cell_as_no_evidence():
    assert parse_repo_array("[]") == ()
    assert parse_repo_array("") == ()
    assert parse_repo_array("   ") == ()
    assert parse_repo_array(None) == ()


def test_parses_a_single_element_array():
    assert parse_repo_array("['koala73/worldmonitor']") == ("koala73/worldmonitor",)


def test_repo_names_with_a_hyphen_and_a_dot_survive_intact():
    """`rinseaid/omniroute` and `simonw/datasette.io` are both real. A naive split on
    punctuation mangles the second and a split on `,` alone is fine only until a name
    contains one."""
    got = parse_repo_array("['pingdotgg/t3-code','simonw/datasette.io','a.b-c/d_e.f-g']")
    assert got == ("pingdotgg/t3-code", "simonw/datasette.io", "a.b-c/d_e.f-g")


def test_an_escaped_quote_inside_a_name_does_not_end_the_element():
    assert parse_repo_array(r"['ow\'ner/repo','b/c']") == ("ow'ner/repo", "b/c")


def test_a_truncated_literal_degrades_to_what_it_could_read_never_raises():
    assert parse_repo_array("['a/b','c/d") == ("a/b",)


# --- T02: the three new columns come off the real cohort row ---------------

def test_the_f019_triple_is_all_three_terms_on_the_real_cohort():
    """F019's SHIP CONDITION: owner count ALONE cannot tell a template bot from a
    prolific contributor, basename diversity can, and the pair is only legible with the
    repo count beside it. All three are recorded, none is a sort key."""
    t = FakeTransport([_fixture_body()])
    m = pool_metrics(["diegosouzapw", "simonw"], windows=(90,), transport=t,
                     sleep=lambda s: None)
    d = m["diegosouzapw"][90]
    assert (d.repos_not_owned, d.not_owned_basenames, d.not_owned_owners) == (124, 2, 124)
    s = m["simonw"][90]
    assert s.repos_not_owned == 13 and s.not_owned_owners < s.repos_not_owned


def test_dominant_base_and_sample_are_parsed_for_the_fork_shaped_accounts():
    t = FakeTransport([_fixture_body()])
    m = pool_metrics(["koala73", "diegosouzapw"], windows=(90,), transport=t,
                     sleep=lambda s: None)
    k = m["koala73"][90]
    assert k.dominant_base == "worldmonitor"
    assert len(k.dominant_repos) >= 5
    assert all("/" in r for r in k.dominant_repos)
    assert any(r.lower() == "koala73/worldmonitor" for r in k.dominant_repos)
    dg = m["diegosouzapw"][90]
    assert dg.dominant_base == "omniroute"
    assert len(dg.dominant_repos) == 30    # groupUniqArray(30) caps the sample


def test_a_missing_new_column_is_a_moved_contract_not_a_transient():
    """The e01 header parses no more. A vanished column raises instead of silently
    zero-filling, because a zero `not_owned_owners` is a real value F019 reads."""
    body = ("actor_login\tpushes\tdistinct_repos\tactive_days\trepos_not_owned\t"
            "not_owned_basenames\tmax_basename_group\tweeks_map\n"
            "someone\t1\t1\t1\t0\t0\t1\t([0],[1])\n")
    t = FakeTransport([body])
    with pytest.raises(GHArchiveUnavailable):
        pool_metrics(["someone"], windows=(90,), transport=t, sleep=lambda s: None)


def test_the_new_fields_ride_the_same_three_scans():
    """Query count is a correctness property: the shared hourly quota is finite and e01
    lost the endpoint for an hour to a second scan. Three new fields, still three POSTs."""
    t = FakeTransport([_fixture_body()])
    pool_metrics(["simonw", "koala73"], transport=t, sleep=lambda s: None)
    assert len(t.sent) == 3
    for sql in t.sent:
        assert "not_owned_owners" in sql and "dominant_repos" in sql
