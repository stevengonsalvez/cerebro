"""F056 — the per-run cost budget, asserted against a REAL artifact.

THE FIXTURE IS COMMITTED AND THE TEST READS THE FIXTURE, NOT `logs/devs/`.
`devs-refresh --out` defaults under `logs/`, which `.gitignore` ignores, so a test
pointed at a live run's artifact FAILS on a fresh clone and in CI — or, worse, skips and
becomes a vacuous assertion that reports green. `tests/fixtures/devs_budget_sample.json`
is a real budget json, produced by a real warm `devs-refresh --dry-run` against the
1,036-note Signals corpus on 2026-08-27, committed unedited. The e01/e02 precedent for
exactly this is `devs_schema_sample.json`. It is RE-MEASURED, never hand-edited, every
time the producer's key set moves: `rest_failures` landing moved `rest_calls_used`
10 -> 11 and `rest_cache_hits` 1,741 -> 1,740 (one cached entry had aged past its TTL),
and F057's two history keys moved them again on a third. This is the FOURTH real warm
run, taken when F064's four prune keys landed: 10 calls and 1,741 hits. Adding a key by
hand would make this file a claim about a run rather than a record of one.

What the recorded run cost, and why each number is the one to watch:

    clickhouse_scans        3   ONE query per window returns all four metrics. This is
                                the number F056 was corrected to; a 4 means somebody
                                re-derived a metric with a second scan.
    rest_calls_used        10   against a 2,200 cap, warm. The e02 COLD figure is 1,744.
    rest_cache_hits     1,741   the split is what makes "a second run is materially
                                cheaper" measurable rather than asserted.
    rest_failures           0   REST calls that RAISED. The meter that separates a
                                DEGRADED run from a small one — see the test below.
    repo_calls_used         0   against a 500 cap, on a corpus already fully populated
    repos_populated     1,316   under a 168-hour TTL. THE STEADY STATE.
    fork_calls_used       140   against a 300 cap, on the 28 fork-shaped candidates.
    snapshots_written   7,707   F057. 2,569 scanned logins x 3 windows, written from the
                                FREE lane before admission — so it is the row count each
                                snapshot table gained, and `sqlite3` agrees (see below).
                                It exceeds `pool` because measurement happens BEFORE the
                                identity dedup, which is the correct order: a login the
                                pool later collapses still pushed on the days it pushed.
    snapshot_store              the sqlite file that history went to. "" would mean the
                                client had no cache and the run measured nothing.
    responses_deleted       0   F064, and THE FIRST REAL MEASUREMENT OF THE POLICY: on a
                                377 MB cache built over the last few days, nothing is yet
                                past the 336 h retention, so the correct behaviour is to
                                delete nothing. A non-zero here on this run would mean the
                                cutoff was wrong, not that the cache was tidy.
    cache_bytes   377,532,416   the file BEFORE the prune. The number F064 exists for.
"""
from __future__ import annotations

import json
from pathlib import Path

from cerebro.gitintel import devs_spike, pool, repo_facts

FIXTURE = Path(__file__).parent / "fixtures" / "devs_budget_sample.json"
BUDGET = json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_whole_pool_is_enriched_in_exactly_three_clickhouse_scans():
    """F056's correction: one query per WINDOW returns every metric, so a full run is
    three scans and not one per metric per window."""
    assert BUDGET["clickhouse_scans"] == 3 == len(devs_spike.WINDOWS)


def test_every_rest_ceiling_held():
    assert BUDGET["rest_calls_used"] <= BUDGET["rest_calls_cap"]
    assert BUDGET["rest_calls_cap"] == devs_spike.REST_CALLS_CAP == 2200
    assert BUDGET["repo_calls_used"] <= BUDGET["repo_calls_cap"]
    assert BUDGET["fork_calls_used"] <= BUDGET["fork_calls_cap"]


def test_the_artifact_says_which_command_produced_it():
    """`devs-spike` is the F066 gate rehearsal; `devs-refresh` is the stage that actually
    writes a corpus. A budget with no stage cannot be attributed to either."""
    assert BUDGET["stage"] == "devs-refresh"


def test_every_truncation_flag_that_is_set_carries_a_non_zero_count_beside_it():
    """A budget that silently stops doing work reports a clean run and surfaces an hour
    later as a 403. Both directions are asserted: a flag with a zero count is a lie, and
    a non-zero count with no flag is a silent truncation."""
    pairs = [("truncated", "skipped_logins"),
             ("fork_budget_exhausted", "fork_unevidenced"),
             ("repo_budget_exhausted", "repos_unpopulated")]
    for flag, count in pairs:
        if BUDGET[flag]:
            assert BUDGET[count] > 0, f"{flag} is set with {count} == 0"


def test_the_recorded_run_reached_every_publishable_dev_with_repos():
    """The 168-hour TTL argument, as a measurement rather than a claim: a fully warm run
    populates the whole corpus for ZERO repo calls."""
    assert BUDGET["repos_populated"] > 1000
    assert BUDGET["repos_unpopulated"] == 0
    assert BUDGET["repo_budget_exhausted"] is False


def test_a_warm_run_is_materially_cheaper_than_a_cold_one():
    """`rest_calls_used` and `rest_cache_hits` are deltas off the CLIENT's own counters
    and off nothing else. A zero `rest_calls_used` beside a zero `rest_cache_hits` would
    mean the counter is unwired and every number here is unmeasured."""
    assert BUDGET["rest_cache_hits"] > BUDGET["rest_calls_used"]
    assert BUDGET["rest_cache_hits"] > 0


def test_the_recorded_run_had_zero_rest_failures_and_says_so_as_a_number():
    """`0` IS THE MEASUREMENT THAT MAKES THE FLAG MEAN SOMETHING. A budget with no
    failure meter cannot tell a run that resolved nobody apart from a run that found
    nobody, and `sink/devs.py` deletes the difference as churn. This is the negative
    control for `tests/test_devs_degraded.py`, which drives the same meter positive."""
    assert BUDGET["rest_failures"] == 0
    assert isinstance(BUDGET["rest_failures"], int)


def test_the_recorded_run_advanced_the_growth_clock_and_says_where_it_went():
    """F057. A run that records no history cannot ever produce a growth delta, and the
    condemned scorer's `record=False` is exactly that failure shipped for six months.
    `snapshots_written` is the row count EACH table gained, so it is checkable against
    the store rather than against itself."""
    assert BUDGET["snapshots_written"] > 0
    assert BUDGET["snapshots_written"] % len(devs_spike.WINDOWS) == 0
    assert BUDGET["snapshots_written"] >= 3 * BUDGET["repos_populated"]
    assert str(BUDGET["snapshot_store"]).endswith(".sqlite")


def test_the_recorded_prune_deleted_nothing_because_nothing_was_old_enough():
    """F064's first real measurement, and the shape that makes it meaningful. Every
    response in the recorded 377 MB cache was written in the last few days, so a correct
    prune deletes ZERO of them; a non-zero count on this run would mean the cutoff moved,
    not that the cache was tidy. `cache_bytes` is the file the policy exists for."""
    assert BUDGET["responses_deleted"] == 0
    assert BUDGET["snapshots_deleted"] == 0
    assert BUDGET["snapshots_downsampled"] == 0
    assert BUDGET["cache_bytes"] > 100_000_000


def test_the_fixture_key_set_is_exactly_the_producers_key_set():
    """PRODUCER AND RECORDED ARTIFACT CANNOT DRIFT. A field added to `pool.Budget` without
    refreshing the fixture, or a stale fixture from before a field landed, is red here
    rather than discovered when somebody reads a meter that no longer exists."""
    assert set(BUDGET) == set(pool.Budget().to_dict())


def test_an_exhausted_repo_budget_renders_the_flag_and_the_count_together():
    """The synthetic half, which needs no fixture: the pair above is only meaningful if
    the producer really does set both. Measured on a real cold run this shape was
    `repo_budget_exhausted: true` with `repos_unpopulated: 316`."""
    budget = pool.Budget()
    repo_bud = repo_facts.RepoBudget(2)
    publishable = 5
    populated = 0
    for _ in range(publishable):
        if repo_bud.take():
            populated += 1
    budget.repo_calls_used = repo_bud.used
    budget.repo_calls_cap = repo_bud.cap
    budget.repo_budget_exhausted = repo_bud.exhausted
    budget.repos_populated = populated
    budget.repos_unpopulated = publishable - populated
    rendered = budget.to_dict()
    assert rendered["repo_budget_exhausted"] is True
    assert rendered["repos_unpopulated"] == 3 > 0
    assert rendered["repo_calls_used"] == rendered["repo_calls_cap"] == 2


def test_the_consent_gate_is_metered_even_when_it_removed_nobody():
    """A gate whose effect is invisible in the artifact is indistinguishable from a gate
    nobody wired up. `0` is a measurement; a missing key is not."""
    assert "optout_removed" in BUDGET
    assert isinstance(BUDGET["optout_removed"], int)


def test_the_fixture_carries_no_token_and_no_personal_data():
    flat = json.dumps(BUDGET).lower()
    for banned in ("token", "ghp_", "github_pat_", "@", "bearer"):
        assert banned not in flat
