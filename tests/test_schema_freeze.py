"""T14 — the roadmap SCHEMA FREEZE, asserted against a REAL record.

e04 builds its index, profile pages and F035 sparklines on this contract and depends on
e01 through it. A fixture committed with a field missing or mistyped does not surprise
e04 at integration time; it silently narrows the contract e04 already built on. So every
frozen field's presence AND type is a build failure here.

The fixture is a real, unredacted, public-data-only record straight out of the
2026-08-26 devs-run json.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "devs_schema_sample.json"
REC = json.loads(FIXTURE.read_text(encoding="utf-8"))

#: A SECOND fixture, deliberately fan-out discovered. e04 builds in parallel with e02 and
#: e01 only ever produced `discovered_via == "vault"`; without a fan-out record to build
#: against, "assume vault" is the easiest possible mistake and it would only surface at
#: integration. This one makes it impossible to miss.
FANOUT_FIXTURE = Path(__file__).parent / "fixtures" / "devs_schema_fanout_sample.json"
FANOUT_REC = json.loads(FANOUT_FIXTURE.read_text(encoding="utf-8"))

#: e02 adds `not_owned_owners`. THE SET BELOW IS COMPARED BY EXACT EQUALITY, so this line
#: and the field that produces it move in the SAME commit — which is the point of the
#: freeze: an additive schema change is a deliberate, recorded, coordinated event rather
#: than something e04 discovers at integration time.
WINDOW_METRICS = ("pushes", "distinct_repos", "active_days", "repos_not_owned",
                  "not_owned_basenames", "not_owned_owners")


def test_every_top_level_frozen_field_is_present():
    frozen = {"login", "name", "discovered_via", "provenance", "windows",
              "pushes_per_week", "automation", "low_n", "repos", "repos_populated",
              "generated_at"}
    assert frozen <= set(REC), f"missing {frozen - set(REC)}"


def test_identity_and_provenance_types():
    assert isinstance(REC["login"], str) and REC["login"]
    assert REC["name"] is None or isinstance(REC["name"], str)
    assert isinstance(REC["discovered_via"], str) and REC["discovered_via"] == "vault"
    assert isinstance(REC["provenance"], list) and REC["provenance"]
    assert all(isinstance(h, str) for h in REC["provenance"])


# --- e02 additions to the frozen contract ------------------------------------

def test_discovered_via_vocabulary_widened_to_three_lanes():
    """e01 could only ever say "vault". e04 must not hard-code that."""
    assert REC["discovered_via"] in {"vault", "roster", "fanout"}
    assert FANOUT_REC["discovered_via"] in {"vault", "roster", "fanout"}
    assert FANOUT_REC["discovered_via"] == "fanout", \
        "the second fixture exists precisely so `vault` cannot be assumed"


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_discovered_via_all_lists_every_lane_and_contains_the_single_string(rec):
    """The single field is a precedence winner; this is the whole set, which is what
    makes the precedence auditable on the published page."""
    all_lanes = rec["discovered_via_all"]
    assert isinstance(all_lanes, list) and all_lanes
    assert all(x in {"vault", "roster", "fanout"} for x in all_lanes)
    assert rec["discovered_via"] in all_lanes
    assert all_lanes == sorted(all_lanes)


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_provenance_repos_says_which_repo_put_the_person_in_the_pool(rec):
    """A fan-out candidate is here because of a REPO, one hop from a signal note, and the
    profile copy must be able to say that honestly. `provenance` alone reads as "the
    vault named this person", which for a fan-out record is FALSE."""
    repos = rec["provenance_repos"]
    assert isinstance(repos, list) and repos
    assert all(isinstance(r, str) and "/" in r for r in repos)


def test_the_fanout_record_carries_a_repo_hop_and_inherited_signal_hashes():
    assert FANOUT_REC["provenance_repos"], "a fan-out record without its repo is unusable"
    assert FANOUT_REC["provenance"], "the hop still inherits the note that cited the repo"


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_facets_are_present_per_window_and_are_never_a_sort_key(rec):
    """F023 display facts. Breadth and depth are recorded SEPARATELY: neither folds into
    one axis, and `distinct_repos` is in the no-composite sweep's VOLUME_NAMES, so
    sorting the index by it is already a build failure."""
    from cerebro.gitintel.facets import FACET_NAMES
    f = rec["facets"]
    assert set(f) == {"7d", "30d", "90d"}
    for window, values in f.items():
        assert set(values) == set(FACET_NAMES), window
        assert isinstance(values["distinct_repos"], int)
        assert isinstance(values["pushes_per_repo"], float)
    for banned in ("score", "rank", "index", "percentile", "grade"):
        assert not any(banned in k for k in f["90d"])


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_automation_carries_the_fork_provenance_slot(rec):
    """Additive: `None` means no fork shape fired, so no evidence was gathered and none
    was needed. A dict means it was, and e04 renders it in the honest-state copy."""
    fp = rec["automation"]["fork_provenance"]
    assert fp is None or isinstance(fp, dict)
    if fp is not None:
        for key in ("checked", "own_upstream", "third_party", "no_upstream",
                    "upstreams", "sampled", "truncated", "unresolved"):
            assert key in fp, key
        assert isinstance(fp["upstreams"], list) and isinstance(fp["sampled"], list)


def test_the_vault_fixture_carries_real_fork_evidence_not_a_placeholder():
    """The whole deliverable of the fork lane is that a reviewer reads upstream NAMES
    instead of a bare ratio. A fixture with an empty evidence block would let e04 build a
    card that renders nothing."""
    fp = REC["automation"]["fork_provenance"]
    assert fp is not None, "the vault fixture must exercise the fork-evidence path"
    assert fp["checked"] > 0 and fp["upstreams"]
    assert any(REC["login"].lower() in u.lower() for u in fp["upstreams"])


def test_a_fork_sub_shape_is_a_flag_name_and_never_a_clearance():
    """ALL THREE SUB-SHAPES ARE FLAGS. `clear` here comes from a recorded human
    `cleared:` verdict, never from the fork evidence."""
    from cerebro.gitintel.admission import FORK_SUBSHAPES
    shapes = REC["automation"]["shapes"]
    assert any(s in FORK_SUBSHAPES for s in shapes), \
        "the fixture must exercise a fork sub-shape"
    assert REC["automation"]["state"] == "clear"
    assert REC["automation"]["cleared_by"], \
        "clear WITH a fired shape must name the human who cleared it"


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_the_prefilter_state_is_recorded_so_unchecked_never_reads_as_checked(rec):
    """`admitted: true` cannot express "nobody looked". A writer that cannot tell a
    REST-verified account from a deferred one would publish both with equal confidence."""
    from cerebro.gitintel.pool import PREFILTER_STATES
    assert rec["automation"]["prefilter"] in set(PREFILTER_STATES)
    # The vocabulary itself is frozen: a producer that invents a fourth spelling of
    # "verified" would slip past the membership check above.
    assert set(PREFILTER_STATES) == {
        "rest_verified", "deferred_below_activity_floor", "deferred_rest_budget",
        "curated_roster"}


def test_windows_has_exactly_the_three_frozen_keys():
    assert set(REC["windows"]) == {"7d", "30d", "90d"}
    assert set(FANOUT_REC["windows"]) == {"7d", "30d", "90d"}


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
@pytest.mark.parametrize("window", ["7d", "30d", "90d"])
def test_each_window_carries_the_frozen_metrics_as_ints(window, rec):
    """EXACT SET EQUALITY, deliberately. e02 adds `not_owned_owners` and this assertion is
    what forces the addition to be recorded rather than absorbed — the constant above and
    the field that produces it move in one commit."""
    w = rec["windows"][window]
    assert set(w) == set(WINDOW_METRICS)
    for k in WINDOW_METRICS:
        assert isinstance(w[k], int), f"{window}.{k} is {type(w[k]).__name__}"
    assert w["active_days"] <= int(window.rstrip("d"))


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_the_f019_triple_is_internally_consistent(rec):
    """A not-owned repo has exactly one owner and one basename, so neither derived count
    can exceed the repo count. A row where it does is a parse bug, not a person."""
    for window in ("7d", "30d", "90d"):
        w = rec["windows"][window]
        assert w["not_owned_owners"] <= w["repos_not_owned"], window
        assert w["not_owned_basenames"] <= w["repos_not_owned"] or w["repos_not_owned"] == 0


def test_pushes_per_week_is_present_populated_and_thirteen_ints():
    """F035's sparkline series. An all-zero or absent series is a FAILED done-condition,
    not a detail: e04 builds the sparkline on it, and it costs nothing because it rides
    on the same single 90d scan."""
    series = REC["pushes_per_week"]
    assert isinstance(series, list)
    assert len(series) == 13
    assert all(isinstance(v, int) for v in series)
    assert any(v > 0 for v in series), "the series must be real, not a placeholder"
    assert sum(series) <= REC["windows"]["90d"]["pushes"]


def test_automation_is_tri_state_with_all_three_shape_evidence_floats():
    """Tri-state plus shape evidence is a Court mandate (F037), not a preference."""
    a = REC["automation"]
    assert a["state"] in {"clear", "flagged", "excluded"}
    for k in ("push_per_day", "not_owned_ratio", "basename_concentration",
              "repo_per_active_day"):
        assert isinstance(a[k], float), f"automation.{k} is {type(a[k]).__name__}"
    assert isinstance(a["shapes"], list)
    assert isinstance(a["shape_evidence"], list)
    assert len(a["shapes"]) == len(a["shape_evidence"])


def test_a_clear_state_from_a_human_verdict_is_distinguishable_from_nothing_firing():
    """Cleared is transparent, not silent: the record must say WHO cleared it and which
    shapes fired, or a published profile cannot explain itself."""
    a = REC["automation"]
    assert "cleared_by" in a and "cleared_on" in a
    if a["shapes"] and a["state"] == "clear":
        assert a["cleared_by"], "a shape fired and resolved clear with no reviewer named"


def test_low_n_is_a_bool_label_not_a_suppression_flag():
    assert isinstance(REC["low_n"], bool)
    assert REC["admitted"] is True or REC["automation"]["state"] != "clear"


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_repos_is_left_exactly_as_e01_left_it(rec):
    """e02 holds a `GET /repos` call for fork provenance and must NOT populate `repos[]`
    opportunistically. That lane is e03's, and e04 branches on `repos_populated`;
    flipping it here with partial data would publish an incomplete repo card as a fact
    about a named human."""
    assert rec["repos"] == []
    assert rec["repos_populated"] is False


def test_repos_ships_empty_with_an_explicit_marker():
    """e01 deliberately does not call the REST repo endpoints every element field needs.
    `[]` on its own is indistinguishable from "this developer has no repos" and would
    publish an empty repo card as a FACT about a named human. The marker is a typed
    placeholder e03 populates and e04 branches on — e04 must render the repo card from
    `repos_populated`, never from `len(repos)`."""
    assert REC["repos"] == []
    assert REC["repos_populated"] is False


def test_reasons_carries_one_audit_line_per_floor():
    assert isinstance(REC["reasons"], list) and len(REC["reasons"]) == 3
    assert REC["reasons"][0].startswith("provenance:")
    assert REC["reasons"][1].startswith("activity:")
    assert REC["reasons"][2].startswith("automation:")


def test_generated_at_is_an_iso_timestamp():
    from datetime import datetime
    datetime.fromisoformat(REC["generated_at"])


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_no_composite_score_field_exists_anywhere_in_the_record(rec):
    flat = json.dumps(rec).lower()
    for banned in ('"score"', '"rank"', '"followers"', '"stars"', '"weight"'):
        assert banned not in flat, f"the frozen record must not carry {banned}"
    assert '"contributions"' not in flat, \
        "the fan-out lane's commit count must not have survived the boundary"


@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_the_fixture_is_public_data_only(rec):
    flat = json.dumps(rec).lower()
    for banned in ("token", "email", "@", "ghp_", "github_pat_"):
        assert banned not in flat
