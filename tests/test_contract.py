"""F069 — the drift alarm, against a verbatim live DESCRIBE and four mutations of it.

FIXTURE PROVENANCE. `gharchive_describe.tsv` is the byte-for-byte body of
`DESCRIBE TABLE github_events FORMAT TSVWithNames` against `play.clickhouse.com` on
2026-08-27: 54 columns, `actor_login`/`repo_name` `LowCardinality(String)`, `created_at`
`DateTime`, `event_type` a 23-member `Enum8` carrying `'PushEvent' = 12`. The four mutated
copies are that file with exactly one thing moved, so a test that goes red names the thing.

THE UNMUTATED FIXTURE MUST PRODUCE NO DRIFT. That is the assertion that keeps this alarm
worth having: one that fires on a healthy schema is one an operator mutes, and a muted
alarm is worse than none.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cerebro.gitintel import contract, gharchive
from cerebro.gitintel.gharchive import GHArchiveContractError, GHArchiveUnavailable

FIX = Path(__file__).parent / "fixtures"
LIVE = (FIX / "gharchive_describe.tsv").read_text(encoding="utf-8")

#: The live liveness row, verbatim, 2026-08-27 03:0x UTC.
LIVE_LIVENESS = "newest_at\tpushes_72h\n2026-08-27 02:59:57\t6450031\n"
NOW = datetime(2026, 8, 27, 7, 0, 0, tzinfo=timezone.utc)


def _mutation(name: str) -> str:
    return (FIX / f"gharchive_describe_{name}.tsv").read_text(encoding="utf-8")


class Transport:
    """Answers DESCRIBE and the liveness aggregate; records what it was asked."""

    def __init__(self, describe=LIVE, liveness=LIVE_LIVENESS):
        self.describe = describe
        self.liveness = liveness
        self.sent: list[str] = []

    def __call__(self, sql):
        self.sent.append(sql)
        if isinstance(self.describe, Exception) and "DESCRIBE" in sql:
            raise self.describe
        return self.describe if "DESCRIBE" in sql else self.liveness


# --- the healthy schema ------------------------------------------------------

def test_the_live_schema_produces_no_drift_at_all():
    assert contract.check_columns(LIVE) == []


def test_the_live_check_names_four_columns_the_enum_member_and_the_feed():
    slept: list[float] = []
    report = contract.run_check(Transport(), now=NOW, sleep=slept.append)
    assert report.ok is True
    assert report.columns_checked == ("actor_login", "repo_name", "created_at",
                                      "event_type")
    assert report.enum_member == "PushEvent"
    assert report.newest_at == "2026-08-27 02:59:57"
    assert report.pushes_72h == 6_450_031
    assert report.drift == []
    assert slept == []


def test_the_check_costs_exactly_two_queries():
    """A FOURTH query per day beside the run's three, and no more. Query count is a
    correctness property on a shared hourly quota, not an optimisation."""
    t = Transport()
    report = contract.run_check(t, now=NOW, sleep=lambda s: None)
    assert report.queries == 2
    assert len(t.sent) == 2
    assert sum("DESCRIBE" in sql for sql in t.sent) == 1


def test_the_describe_query_scans_no_rows():
    """`DESCRIBE TABLE` is metadata: 0.08 s, 0 rows (registry s5). The alarm must not
    itself be a scan of the table it is guarding."""
    assert "DESCRIBE TABLE github_events" in contract.DESCRIBE_SQL
    assert "WHERE" not in contract.DESCRIBE_SQL


def test_only_the_four_read_columns_are_asserted():
    """54 columns exist. Asserting the 50 this lane never reads makes the alarm fire on
    upstream changes that cannot affect us."""
    declared = contract.parse_describe(LIVE)
    assert len(declared) == 54
    assert len(contract.EXPECTED_COLUMNS) == 4
    for name, _ in contract.EXPECTED_COLUMNS:
        assert name in declared
        assert name in gharchive.POOL_SQL


# --- one mutation at a time --------------------------------------------------

def test_a_deleted_column_is_named_drift():
    drift = contract.check_columns(_mutation("missing_actor"))
    assert [d.subject for d in drift] == ["actor_login"]
    assert "gone" in drift[0].detail


def test_a_retyped_column_is_drift_and_says_both_types():
    drift = contract.check_columns(_mutation("retyped_created_at"))
    assert [d.subject for d in drift] == ["created_at"]
    assert "DateTime" in drift[0].detail and "UInt64" in drift[0].detail


def test_an_enum_that_lost_pushevent_is_drift_and_explains_the_consequence():
    """The quietest possible catastrophe: the query still runs and every login in the
    pool returns zero rows, which publishes as "2,568 people stopped shipping"."""
    drift = contract.check_columns(_mutation("enum_lost_pushevent"))
    assert [d.subject for d in drift] == ["event_type"]
    assert "zero rows" in drift[0].detail


def test_dropping_the_lowcardinality_wrapper_is_tolerated():
    """THE NEGATIVE CONTROL FOR THE TYPE RULE. `LowCardinality(String)` -> `String` is an
    upstream encoding decision that changes nothing this lane depends on. An alarm that
    fires on it is one that gets muted before it ever catches a real break."""
    assert contract.check_columns(_mutation("plain_string_actor")) == []


def test_a_body_that_is_not_a_describe_fails_loud_rather_than_open():
    drift = contract.check_columns("<html>503 Service Unavailable</html>")
    assert drift and drift[0].subject == "github_events"


@pytest.mark.parametrize("declared,expected", [
    ("LowCardinality(String)", "String"),
    ("Nullable(LowCardinality(String))", "String"),
    ("String", "String"),
    ("DateTime", "DateTime"),
    ("Enum8('A' = 1)", "Enum8"),
    ("UInt64", "UInt64"),
])
def test_base_type_unwraps_encodings_and_keeps_the_parametric_head(declared, expected):
    assert contract.base_type(declared) == expected


def test_the_tsv_escaping_is_undone_before_the_enum_is_read():
    """The raw cell carries `\\'PushEvent\\'`. Reading it unescaped would make the enum
    check fire on every healthy run."""
    raw = contract.parse_describe(LIVE)["event_type"]
    assert "'PushEvent' = 12" in raw
    assert "\\'" not in raw


# --- liveness ----------------------------------------------------------------

def test_the_live_feed_is_inside_both_bounds():
    assert contract.check_liveness(6_450_031, "2026-08-27 02:59:57", now=NOW) == []


def test_a_stalled_feed_is_drift_and_says_how_old():
    stale = (NOW - timedelta(hours=60)).strftime("%Y-%m-%d %H:%M:%S")
    drift = contract.check_liveness(6_450_031, stale, now=NOW)
    assert [d.subject for d in drift] == ["newest_at"]
    assert "stalled" in drift[0].detail


def test_the_lag_bound_has_an_order_of_magnitude_of_slack_over_the_measured_lag():
    """Measured ingest lag on 2026-08-27 was ~4 h. The bound is 48."""
    measured_lag_hours = (NOW - datetime(2026, 8, 27, 2, 59, 57, tzinfo=timezone.utc)
                          ).total_seconds() / 3600
    assert contract.MAX_FEED_LAG_HOURS > 8 * measured_lag_hours


def test_a_collapsed_count_is_drift_and_names_the_floor():
    drift = contract.check_liveness(500, "2026-08-27 02:59:57", now=NOW)
    assert [d.subject for d in drift] == ["pushes_72h"]
    assert str(contract.MIN_PUSHES_72H) in drift[0].detail


def test_the_volume_floor_is_two_orders_below_the_measured_volume():
    assert contract.MIN_PUSHES_72H < 6_450_031 / 60


def test_an_unparseable_newest_at_is_drift_not_a_crash():
    drift = contract.check_liveness(6_450_031, "not a timestamp", now=NOW)
    assert [d.subject for d in drift] == ["newest_at"]


def test_the_liveness_row_parses_and_a_broken_one_is_zero():
    assert contract.parse_liveness(LIVE_LIVENESS) == ("2026-08-27 02:59:57", 6_450_031)
    assert contract.parse_liveness("") == ("", 0)
    assert contract.parse_liveness("newest_at\tpushes_72h\n") == ("", 0)


# --- the two failure classes stay different ----------------------------------

def test_a_drift_body_from_the_endpoint_raises_the_contract_type_without_sleeping():
    slept: list[float] = []
    t = Transport(describe="Code: 60. DB::Exception: Table missing (UNKNOWN_TABLE)\n")
    with pytest.raises(GHArchiveContractError):
        contract.run_check(t, now=NOW, sleep=slept.append)
    assert slept == []


def test_a_transport_outage_raises_unavailable_and_is_not_contract_drift():
    slept: list[float] = []
    t = Transport(describe=OSError("connection refused"))
    with pytest.raises(GHArchiveUnavailable) as exc:
        contract.run_check(t, now=NOW, sleep=slept.append)
    assert not isinstance(exc.value, GHArchiveContractError)
    assert slept == list(gharchive.TRANSPORT_LADDER_S)


def test_the_offline_mode_reads_a_fixture_and_makes_no_query():
    """So the failure path is testable without pretending the endpoint is down."""
    report = contract.run_check(offline_describe=_mutation("missing_actor"))
    assert report.queries == 0
    assert report.ok is False
    assert report.liveness_checked is False
    assert [d.subject for d in report.drift] == ["actor_login"]


def test_the_offline_mode_on_the_live_fixture_is_green():
    report = contract.run_check(offline_describe=LIVE)
    assert report.ok is True and report.drift == []


def test_the_report_serialises_every_field_a_page_needs():
    payload = contract.run_check(Transport(), now=NOW, sleep=lambda s: None).to_dict()
    assert set(payload) == {"ok", "columns_checked", "enum_member", "newest_at",
                            "pushes_72h", "liveness_checked", "drift", "queries"}


def test_the_module_never_sees_a_login():
    """A contract check that took the pool as input would be a fourth scan of the table,
    and a place a ranking line could arrive."""
    src = Path("cerebro/gitintel/contract.py").read_text(encoding="utf-8")
    assert "actor_login IN" not in src
    assert "logins" not in src
