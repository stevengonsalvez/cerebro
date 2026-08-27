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

#: A THIRD fixture, and the one e03 exists to make possible: a real publish-set record
#: with `repos_populated: true` and a populated `repos[]` of real public repo metadata.
#: e01 and e02 could only ever produce `[]` with the marker false, so a corpus where the
#: repo card actually renders had nothing to build against until this file existed.
REPOS_FIXTURE = Path(__file__).parent / "fixtures" / "devs_schema_repos_sample.json"
REPOS_REC = json.loads(REPOS_FIXTURE.read_text(encoding="utf-8"))

#: The frozen `repos[]` element key set, transcribed from the site's `REPO_SNAKE` in
#: `lib/vault/devs.ts`. The loader over there asserts it by EXACT equality, so an extra
#: key is a build-killing throw and a missing one is a throw at `sealRepo`.
REPO_SNAKE = ("name", "title", "description", "language", "topics", "stars_fact",
              "first_seen", "last_push")

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


# --- e03: `repos[]` is POPULATED, and the marker still tells the truth ---------
#
# THIS REPLACES `test_repos_is_left_exactly_as_e01_left_it`, WHICH EXISTED TO FORCE THIS
# COORDINATION. Its own docstring said the lane was e03's; the lane has landed, so the
# assertion moves from "nobody populated this" to "the two states are distinguishable
# and both are honest". The e01/e02 fixtures still carry the unpopulated shape, because
# that is what those runs really produced and e04 renders the empty state from them.

@pytest.mark.parametrize("rec", [REC, FANOUT_REC])
def test_the_e01_and_e02_fixtures_still_carry_the_unpopulated_shape(rec):
    """Those runs never called the repo endpoints, so `[]` with the marker false is what
    they really produced. e04 renders the empty state from exactly this."""
    assert rec["repos"] == []
    assert rec["repos_populated"] is False


def test_the_marker_is_what_distinguishes_populated_from_nobody_looked():
    """`[]` on its own is indistinguishable from "this developer has no repos" and would
    publish an empty repo card as a FACT about a named human. e04 must render the card
    from `repos_populated`, never from `len(repos)`, and the two fixtures side by side
    are what makes that testable over there."""
    assert REPOS_REC["repos_populated"] is True and REPOS_REC["repos"]
    assert REC["repos_populated"] is False and REC["repos"] == []


def test_the_populated_fixture_is_a_real_publish_set_record():
    """A fixture that could not be published is a fixture e04 must never render. This one
    passes the site's own three clauses, which is why a repo card exists for it at all."""
    from cerebro.gitintel.pool import PREFILTER_UNCHECKED
    assert REPOS_REC["admitted"] is True
    assert REPOS_REC["automation"]["state"] == "clear"
    assert REPOS_REC["automation"]["prefilter"] not in PREFILTER_UNCHECKED
    assert REPOS_REC["provenance"], "floor 1: every published profile answers 'why here'"


def test_every_repo_element_carries_exactly_the_frozen_keys_with_the_right_types():
    repos = REPOS_REC["repos"]
    assert 1 <= len(repos) <= 6
    for repo in repos:
        assert set(repo) == set(REPO_SNAKE), repo.get("name")
        assert isinstance(repo["name"], str) and repo["name"]
        assert isinstance(repo["title"], str) and repo["title"]
        assert repo["description"] is None or isinstance(repo["description"], str)
        assert repo["language"] is None or isinstance(repo["language"], str)
        assert isinstance(repo["topics"], list)
        assert all(isinstance(t, str) for t in repo["topics"])
        assert repo["stars_fact"] is None or isinstance(repo["stars_fact"], int)
        assert repo["first_seen"] is None or isinstance(repo["first_seen"], str)
        assert repo["last_push"] is None or isinstance(repo["last_push"], str)


def test_stars_fact_is_the_only_magnitude_anywhere_in_the_populated_record():
    """The frozen name is `stars_fact`, and it is a rendered fact only. A key spelled
    `stars` or `stargazers_count` anywhere in the record is the ruling being lost."""
    flat = json.dumps(REPOS_REC)
    assert '"stars"' not in flat and '"stargazers_count"' not in flat
    assert any(r["stars_fact"] is not None for r in REPOS_REC["repos"])


def test_the_repo_cap_holds_and_the_selection_is_not_star_ordered():
    """F033: stars are a displayed fact, never a sort key. The recorded order is the
    API's recency order, so the star counts in it are NOT descending."""
    stars = [r["stars_fact"] or 0 for r in REPOS_REC["repos"]]
    assert len(stars) <= 6
    assert stars != sorted(stars, reverse=True) or len(set(stars)) <= 1, \
        "the fixture must not be star-ordered, or it proves nothing about the selection"


def test_first_seen_is_the_vaults_own_capture_and_is_null_when_it_never_cited_the_repo():
    """The field means "when the vault first saw this repo", never GitHub's `created_at`.
    Most repos a dev owns were never cited by a Signal note, so `null` is the normal
    value and the fixture carries both cases."""
    seen = [r["first_seen"] for r in REPOS_REC["repos"]]
    assert any(x is not None for x in seen), "the fixture must exercise the cited case"
    assert any(x is None for x in seen), "and the uncited case, which is the common one"


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


# --- e06/D2: the freeze, asserted against a note the WRITER actually produced ------
#
# WHY THIS ADDITION IS REQUIRED AND WHY IT IS THE OPPOSITE OF WEAKENING THE FREEZE.
# Everything above this line reads a committed JSON *fixture*, and the top-level check at
# `test_every_top_level_frozen_field_is_present` is `frozen <= set(REC)` — a SUBSET. It
# passes silently when a field is ADDED, which is exactly the direction e06 must not move
# in: e07 is building against this schema in parallel and the site's loader THROWS on a
# producer field that is on neither its ADMITTED nor its CONSUMED list. Nothing anywhere
# in this suite read a note the writer had actually produced.
#
# So this asserts the frontmatter key set of a REAL WRITTEN NOTE by EXACT EQUALITY,
# against a constant transcribed from e03's output. Adding `growth` or `freshness` to the
# record — the two enrichments e06 computes — fails here, in this repository, instead of
# reddening a build in another one.

#: The 16 frontmatter keys e03 writes, transcribed from a produced note. NOT imported from
#: `sink/devs.FRONTMATTER_KEYS`: a constant compared against itself asserts nothing, and
#: the whole point is to catch an edit to that tuple.
WRITTEN_FRONTMATTER_KEYS = {
    "login", "name", "discovered_via", "discovered_via_all", "provenance_repos",
    "admitted", "low_n", "repos_populated", "generated_at", "provenance",
    "pushes_per_week", "windows", "automation", "facets", "reasons", "repos",
}


def _write_one_note(tmp_path, record):
    """Through the REAL writer, into a tmp vault. Returns the note's text."""
    from cerebro.sink import devs as devs_sink

    root = tmp_path / "vault"
    corpus_plan = devs_sink.plan([record], [], optout=None, verdicts=None)
    assert corpus_plan.writes, "the fixture record is not publishable; the test would be vacuous"
    devs_sink.apply(corpus_plan, root)
    note = root / devs_sink.CORPUS_DIR / f"{record['login']}.md"
    assert note.is_file(), "the writer produced no note"
    return note.read_text(encoding="utf-8")


def _frontmatter_keys(text: str) -> set:
    import re

    assert text.startswith("---\n"), "no frontmatter"
    body = text.split("---\n", 2)[1]
    return {m.group(1) for m in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*):", body,
                                            flags=re.MULTILINE)}


def test_a_written_notes_frontmatter_key_set_is_exactly_the_frozen_one(tmp_path):
    """EXACT EQUALITY, over a note on disk. A new producer field lands here."""
    keys = _frontmatter_keys(_write_one_note(tmp_path, dict(REPOS_REC)))
    assert keys == WRITTEN_FRONTMATTER_KEYS, {
        "added": sorted(keys - WRITTEN_FRONTMATTER_KEYS),
        "missing": sorted(WRITTEN_FRONTMATTER_KEYS - keys),
    }


def test_the_written_key_set_matches_the_serializers_own_tuple(tmp_path):
    """The two must agree, and they are compared rather than shared: if a field is added
    to `FRONTMATTER_KEYS` this fails, which is the point."""
    from cerebro.sink.devs import FRONTMATTER_KEYS

    assert set(FRONTMATTER_KEYS) == WRITTEN_FRONTMATTER_KEYS


def test_the_writer_refuses_an_e06_enrichment_field_outright(tmp_path):
    """D2 AS A MECHANISM RATHER THAN A PARAGRAPH. `growth` and `freshness` are computed by
    this epic and land in `logs/devs/` artifacts. Putting either on the record is a
    build-killing throw in the site's loader; here it is a `ValueError` before a byte is
    written."""
    from cerebro.sink import devs as devs_sink

    for field_name in ("growth", "freshness"):
        record = dict(REPOS_REC)
        record[field_name] = {"delta": None}
        with pytest.raises(ValueError) as exc:
            devs_sink.render(record)
        assert field_name in str(exc.value)
        assert "coordination event" in str(exc.value)


def test_the_negative_control_a_removed_field_is_also_caught(tmp_path):
    """A key-set assertion that only catches additions is half a gate."""
    from cerebro.sink import devs as devs_sink

    record = dict(REPOS_REC)
    record.pop("facets")
    with pytest.raises(ValueError):
        devs_sink.render(record)


def test_e06s_enrichments_are_absent_from_every_committed_fixture():
    """The other direction: no fixture may quietly acquire the fields either, or the
    assertion above would be asserting against a moved target."""
    for fixture in (REC, FANOUT_REC, REPOS_REC):
        assert "growth" not in fixture and "freshness" not in fixture
