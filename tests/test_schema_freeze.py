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

WINDOW_METRICS = ("pushes", "distinct_repos", "active_days", "repos_not_owned",
                  "not_owned_basenames")


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


def test_windows_has_exactly_the_three_frozen_keys():
    assert set(REC["windows"]) == {"7d", "30d", "90d"}


@pytest.mark.parametrize("window", ["7d", "30d", "90d"])
def test_each_window_carries_the_five_frozen_metrics_as_ints(window):
    w = REC["windows"][window]
    assert set(w) == set(WINDOW_METRICS)
    for k in WINDOW_METRICS:
        assert isinstance(w[k], int), f"{window}.{k} is {type(w[k]).__name__}"
    assert w["active_days"] <= int(window.rstrip("d"))


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


def test_no_composite_score_field_exists_anywhere_in_the_record():
    flat = json.dumps(REC).lower()
    for banned in ('"score"', '"rank"', '"followers"', '"stars"', '"weight"'):
        assert banned not in flat, f"the frozen record must not carry {banned}"


def test_the_fixture_is_public_data_only():
    flat = json.dumps(REC).lower()
    for banned in ("token", "email", "@", "ghp_", "github_pat_"):
        assert banned not in flat
