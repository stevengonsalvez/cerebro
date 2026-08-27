"""The write gate and the reconciling writer.

THE WRITE GATE IS THE PUBLISH GATE. `cerebro-vault` is public, so a record written into
`Devs/` is published data about a named human whether or not a page renders from it.
Every assertion here is about what does NOT get written.
"""
from __future__ import annotations

import copy
import json
import types
from pathlib import Path

import pytest

from cerebro.gitintel import denylist, optout, pool
from cerebro.sink import devs

FIXTURES = Path(__file__).parent / "fixtures"
REC = json.loads((FIXTURES / "devs_schema_sample.json").read_text(encoding="utf-8"))

#: The REAL verdicts file every run reads, and the real (empty) consent file.
VERDICTS = denylist.load(denylist.DEFAULT_PATH)
NO_ONE = optout.EMPTY


def rec(**over) -> dict:
    out = copy.deepcopy(REC)
    for key, value in over.items():
        if key in ("state", "prefilter"):
            out["automation"][key] = value
        else:
            out[key] = value
    return out


def consent(*logins) -> optout.OptOut:
    return optout.OptOut(logins=frozenset(optout.slug(x) for x in logins))


# --- the six clauses, one at a time ------------------------------------------

def test_a_clean_record_is_publishable():
    """Negative control for everything below: without this, a gate that withheld
    everybody would pass every other test in this section."""
    ok, reason = devs.publishable(rec(), optout=NO_ONE, verdicts=VERDICTS)
    assert ok is True and reason == ""


def test_a_flagged_record_is_withheld_and_the_reason_names_the_tri_state():
    ok, reason = devs.publishable(rec(state="flagged"), optout=NO_ONE,
                                  verdicts=VERDICTS)
    assert ok is False and reason == "automation: flagged"


def test_an_excluded_record_is_withheld():
    ok, reason = devs.publishable(rec(state="excluded"), optout=NO_ONE,
                                  verdicts=VERDICTS)
    assert ok is False and reason == "automation: excluded"


@pytest.mark.parametrize("marker", pool.PREFILTER_UNCHECKED)
def test_an_account_nobody_ever_checked_is_withheld(marker):
    """"A call was intended and never made". Publishing it would render an unchecked
    account exactly as it renders a verified one."""
    ok, reason = devs.publishable(rec(prefilter=marker), optout=NO_ONE,
                                  verdicts=VERDICTS)
    assert ok is False and reason == f"prefilter: {marker}"


def test_a_prefilter_marker_outside_the_frozen_vocabulary_withholds():
    """Drift about a named person is not something to guess at."""
    ok, reason = devs.publishable(rec(prefilter="probably_fine"), optout=NO_ONE,
                                  verdicts=VERDICTS)
    assert ok is False


def test_a_curated_roster_marker_publishes_because_no_call_was_ever_owed():
    """F008. The fourth marker is NOT a deferral: a human wrote the login into
    config/cracked_devs.yaml, so nothing was deferred and there is no remedy to apply.
    Withholding on it would suppress the owner's own list."""
    ok, _ = devs.publishable(rec(prefilter=pool.PREFILTER_ROSTER), optout=NO_ONE,
                             verdicts=VERDICTS)
    assert ok is True


def test_a_record_with_no_provenance_is_withheld_by_floor_one():
    ok, reason = devs.publishable(rec(provenance=[]), optout=NO_ONE, verdicts=VERDICTS)
    assert ok is False and reason == devs.REASON_PROVENANCE


def test_an_opted_out_login_is_withheld_whatever_else_is_true():
    ok, reason = devs.publishable(rec(), optout=consent(REC["login"]),
                                  verdicts=VERDICTS)
    assert ok is False and reason == devs.REASON_OPTED_OUT


def test_consent_outranks_every_quality_reason_in_the_report():
    """A person who asked to be removed is never characterised in the withheld report by
    a judgement about their account."""
    ok, reason = devs.publishable(rec(state="flagged", provenance=[]),
                                  optout=consent(REC["login"]), verdicts=VERDICTS)
    assert ok is False and reason == devs.REASON_OPTED_OUT


# --- the sixth clause, against the real stale record --------------------------

STALE_DENIED = json.loads(
    (FIXTURES / "devs_record_stale_denied.json").read_text(encoding="utf-8"))


def test_the_stale_record_really_does_pass_the_other_five_clauses():
    """THE FIXTURE IS ONLY INTERESTING IF THIS IS TRUE. `GCGH159` was written into the
    2026-08-27 run json BEFORE his `denied:` verdict landed, so the record still says
    admitted / clear / rest_verified / provenance 1. Strip the verdict and he publishes.
    That is the hole clause six closes, measured rather than imagined."""
    assert STALE_DENIED["admitted"] is True
    assert STALE_DENIED["automation"]["state"] == "clear"
    assert STALE_DENIED["automation"]["prefilter"] == pool.PREFILTER_VERIFIED
    assert len(STALE_DENIED["provenance"]) == 1
    ok, _ = devs.publishable(STALE_DENIED, optout=NO_ONE, verdicts=denylist.EMPTY)
    assert ok is True, "with no verdicts loaded the stale record IS publishable"


def test_the_stale_record_is_withheld_once_the_real_verdicts_file_is_read():
    ok, reason = devs.publishable(STALE_DENIED, optout=NO_ONE, verdicts=VERDICTS)
    assert ok is False and reason == devs.REASON_DENIED


def test_every_denied_login_in_the_shipped_file_is_unpublishable():
    """Read out of the file, never transcribed, so a verdict recorded tomorrow is covered
    the day it lands."""
    assert VERDICTS.denied, "the assertion is vacuous with an empty verdicts file"
    for login in VERDICTS.denied:
        ok, reason = devs.publishable(rec(login=login), optout=NO_ONE,
                                      verdicts=VERDICTS)
        assert ok is False and reason == devs.REASON_DENIED, login


# --- the corpus-level view ----------------------------------------------------

def test_publish_set_and_withheld_partition_the_input_exactly():
    records = [rec(login="a"), rec(login="b", state="flagged"),
               rec(login="c", provenance=[])]
    kept = devs.publish_set(records, optout=NO_ONE, verdicts=VERDICTS)
    held = devs.withheld(records, optout=NO_ONE, verdicts=VERDICTS)
    assert [r["login"] for r in kept] == ["a"]
    assert held == [("b", "automation: flagged"), ("c", devs.REASON_PROVENANCE)]
    assert len(kept) + len(held) == len(records)


def test_the_publish_set_preserves_input_order():
    """The caller supplies the F063 recurrence work order. Re-sorting here would spend a
    truncated repo budget somewhere other than where the corpus points."""
    records = [rec(login=x) for x in ("zed", "alice", "mallory")]
    assert [r["login"] for r in devs.publish_set(
        records, optout=NO_ONE, verdicts=VERDICTS)] == ["zed", "alice", "mallory"]


def test_a_roster_only_dev_can_only_ever_fail_the_provenance_floor():
    """F008 is NOT weakened by floor 1. A roster dev is never withheld for a QUALITY
    reason — not for low_n, not for a fired shape, not for a deferral — and the only
    floor they can fail is the one that asks "why is this person here at all"."""
    roster = rec(login="t3dotgg", provenance=[], provenance_repos=[],
                 discovered_via="roster", discovered_via_all=["roster"],
                 prefilter=pool.PREFILTER_ROSTER, low_n=True, admitted=False)
    ok, reason = devs.publishable(roster, optout=NO_ONE, verdicts=VERDICTS)
    assert ok is False and reason == devs.REASON_PROVENANCE
    # Give the same roster dev one vault citation and nothing else changes: he publishes.
    cited = dict(roster, provenance=["c489e6fb5febf2ab"], admitted=True)
    assert devs.publishable(cited, optout=NO_ONE, verdicts=VERDICTS)[0] is True


def test_low_n_is_a_label_and_never_a_reason_to_withhold():
    """The bcherny gap. 4 active days in 90d, labelled, published."""
    ok, _ = devs.publishable(rec(low_n=True), optout=NO_ONE, verdicts=VERDICTS)
    assert ok is True


# --- the gate against the real planning artifact ------------------------------

def test_the_gate_reads_the_vocabulary_from_the_producer_not_a_copy():
    """A restated constant is a constant that drifts. The site restates pool.py's tuple
    in TypeScript and the roadmap records that as a coordination event; python has no
    excuse to."""
    import inspect
    src = inspect.getsource(devs.publishable)
    assert "PREFILTER_UNCHECKED" in src and "pool." in src
    assert "deferred_below_activity_floor" not in src


# --- the reconciling writer ----------------------------------------------------

def scratch_vault(tmp_path, *, devs=(), other=True) -> Path:
    """A vault root holding Daily/, Signals/, Weekly/ and some Devs/ notes."""
    root = tmp_path / "vault"
    (root / "Devs").mkdir(parents=True)
    for login in devs:
        (root / "Devs" / f"{login}.md").write_text(
            devs_note(login), encoding="utf-8")
    if other:
        for sub, name in (("Daily", "2026-08-27.md"), ("Signals", "abc.md"),
                          ("Weekly", "2026-w35.md")):
            (root / sub).mkdir(parents=True, exist_ok=True)
            (root / sub / name).write_text(f"{sub} content\n", encoding="utf-8")
    return root


def devs_note(login: str) -> str:
    return devs.render(rec(login=login))


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def settings_for(root, dry_run=True):
    return types.SimpleNamespace(vault_path=root, dry_run=dry_run)


# --- deletions: the two rules ---------------------------------------------------

def test_a_consent_delete_fires_on_a_healthy_run():
    got = devs.plan([rec(login="keepme")], ["keepme", "removeme"],
                    optout=consent("removeme"), verdicts=VERDICTS, healthy=True)
    assert got.deletes_consent == ["removeme"]
    assert [r["login"] for r in got.writes] == ["keepme"]


def test_a_consent_delete_fires_on_an_UNHEALTHY_run_too():
    """THE WHOLE POINT. A person who asked to be removed must be removed even when the
    lane half-failed. Consent deletions are exempt from every guard below."""
    got = devs.plan([rec(login="keepme")], ["keepme", "removeme"],
                    optout=consent("removeme"), verdicts=VERDICTS, healthy=False)
    assert got.deletes_consent == ["removeme"]
    assert got.refused_reason == devs.REFUSED_UNHEALTHY
    assert got.deletes_churn == []


def test_a_denied_verdict_is_a_consent_class_delete():
    """The DELETE half of the sixth clause. `GCGH159` carries a recorded verdict, so a
    note for him on disk is removed even though nobody asked."""
    denied = sorted(VERDICTS.denied)[0]
    got = devs.plan([rec(login="keepme")], ["keepme", denied],
                    optout=NO_ONE, verdicts=VERDICTS, healthy=True)
    assert got.deletes_consent == [denied]


def test_a_denied_login_is_deleted_and_not_re_written_in_the_same_run():
    """Without clause six this exact plan would delete GCGH159 and re-write him from the
    same publish set. The record is the REAL stale one, off the run artifact."""
    got = devs.plan([STALE_DENIED], ["GCGH159"], optout=NO_ONE, verdicts=VERDICTS,
                    healthy=True)
    assert got.deletes_consent == ["GCGH159"]
    assert [devs.slug(r["login"]) for r in got.writes] == []


def test_the_belt_raises_when_the_gate_is_weakened_to_five_clauses(monkeypatch):
    """Proves the assertion in plan() is load-bearing rather than decorative: with
    publishable() monkeypatched back to the five-clause form, the denied login reaches
    writes and plan() refuses to hand it to apply()."""
    monkeypatch.setattr(devs, "publish_set", lambda records, **kw: list(records))
    with pytest.raises(AssertionError, match="sixth clause"):
        devs.plan([STALE_DENIED], [], optout=NO_ONE, verdicts=VERDICTS, healthy=True)


def test_churn_deletes_fire_on_a_healthy_run_and_only_then():
    on_disk = ["keepme"] + [f"gone{i}" for i in range(5)]
    healthy = devs.plan([rec(login="keepme")], on_disk, optout=NO_ONE,
                        verdicts=VERDICTS, healthy=True)
    assert sorted(healthy.deletes_churn) == sorted(f"gone{i}" for i in range(5))
    sick = devs.plan([rec(login="keepme")], on_disk, optout=NO_ONE,
                     verdicts=VERDICTS, healthy=False)
    assert sick.deletes_churn == [] and sick.refused_reason == devs.REFUSED_UNHEALTHY


def test_the_churn_cap_refuses_wholesale_and_keeps_the_corpus():
    """A degraded morning must not silently unpublish hundreds of real people. Wholesale
    rather than partial: half a reconciliation agrees with neither run."""
    on_disk = [f"dev{i}" for i in range(200)]
    got = devs.plan([rec(login="dev0")], on_disk, optout=NO_ONE, verdicts=VERDICTS,
                    healthy=True)
    assert got.deletes_churn == []
    assert got.refused_reason == devs.REFUSED_CHURN_CAP


def test_a_churn_delete_just_under_the_cap_still_executes():
    """Negative control for the cap: without it the test above would pass against a
    writer that never deletes anything."""
    on_disk = [f"dev{i}" for i in range(100)]
    keep = [rec(login=f"dev{i}") for i in range(76)]
    got = devs.plan(keep, on_disk, optout=NO_ONE, verdicts=VERDICTS, healthy=True)
    assert len(got.deletes_churn) == 24 <= devs.churn_cap(100)
    assert got.refused_reason == ""


def test_an_empty_publish_set_writes_nothing_and_deletes_no_churn():
    got = devs.plan([], ["a", "b", "c"], optout=NO_ONE, verdicts=VERDICTS,
                    healthy=True)
    assert got.writes == [] and got.deletes_churn == []
    assert got.refused_reason == devs.REFUSED_EMPTY


def test_an_empty_publish_set_still_honours_a_removal_request():
    got = devs.plan([], ["a", "removeme"], optout=consent("removeme"),
                    verdicts=VERDICTS, healthy=True)
    assert got.deletes_consent == ["removeme"]
    assert got.refused_reason == devs.REFUSED_EMPTY


def test_plan_is_pure(tmp_path):
    """No clock, no disk, no network. Called twice with the same input it returns the
    same answer, and it creates nothing."""
    before = sorted(tmp_path.rglob("*"))
    a = devs.plan([rec(login="x")], ["x", "y"], optout=NO_ONE, verdicts=VERDICTS)
    b = devs.plan([rec(login="x")], ["x", "y"], optout=NO_ONE, verdicts=VERDICTS)
    assert a == b
    assert sorted(tmp_path.rglob("*")) == before


# --- apply(): what actually touches disk ----------------------------------------

def test_apply_writes_deletes_and_leaves_the_rest_of_the_vault_alone(tmp_path):
    root = scratch_vault(tmp_path, devs=["stale"])
    outside = {k: v for k, v in snapshot(root).items() if not k.startswith("Devs/")}
    got = devs.plan([rec(login="fresh")], ["stale"], optout=NO_ONE, verdicts=VERDICTS)
    result = devs.apply(got, root)
    assert result["written"] == ["fresh"] and result["deleted"] == ["stale"]
    assert (root / "Devs" / "fresh.md").is_file()
    assert not (root / "Devs" / "stale.md").exists()
    after = {k: v for k, v in snapshot(root).items() if not k.startswith("Devs/")}
    assert after == outside, "the writer owns Devs/*.md and nothing else"


def test_an_empty_plan_never_creates_the_directory(tmp_path):
    """The site treats an existing but EMPTY Devs/ as a broken clone and makes it a
    build-killing throw. A bad CEREBRO morning must not be able to cause that."""
    root = tmp_path / "vault"
    root.mkdir()
    got = devs.plan([], [], optout=NO_ONE, verdicts=VERDICTS)
    devs.apply(got, root)
    assert not (root / "Devs").exists()


def test_a_note_whose_only_difference_is_the_timestamp_is_left_untouched(tmp_path):
    """1.6. Otherwise 1,300 notes rewrite every morning and the public vault's history
    stops meaning anything."""
    root = scratch_vault(tmp_path, devs=["esengine"])
    before = (root / "Devs" / "esengine.md").stat().st_mtime_ns
    restamped = rec(login="esengine", generated_at="2099-01-01T00:00:00+00:00")
    result = devs.apply(
        devs.plan([restamped], ["esengine"], optout=NO_ONE, verdicts=VERDICTS), root)
    assert result["unchanged"] == ["esengine"] and result["written"] == []
    assert (root / "Devs" / "esengine.md").stat().st_mtime_ns == before
    assert "2099" not in (root / "Devs" / "esengine.md").read_text(encoding="utf-8")


def test_a_note_whose_numbers_moved_is_rewritten_with_the_new_timestamp(tmp_path):
    """Negative control for the test above."""
    root = scratch_vault(tmp_path, devs=["esengine"])
    moved = rec(login="esengine", generated_at="2099-01-01T00:00:00+00:00")
    moved["windows"]["90d"]["pushes"] += 1
    result = devs.apply(
        devs.plan([moved], ["esengine"], optout=NO_ONE, verdicts=VERDICTS), root)
    assert result["written"] == ["esengine"] and result["unchanged"] == []
    text = (root / "Devs" / "esengine.md").read_text(encoding="utf-8")
    assert "2099-01-01" in text


def test_the_written_note_is_exactly_what_the_renderer_produced(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    record = rec(login="esengine")
    devs.apply(devs.plan([record], [], optout=NO_ONE, verdicts=VERDICTS), root)
    assert (root / "Devs" / "esengine.md").read_text(encoding="utf-8") \
        == devs.render(record)


def test_a_stale_temp_file_is_swept_before_anything_is_written(tmp_path):
    """`git add -- Devs` would otherwise push a power-loss stump to a PUBLIC repo."""
    root = scratch_vault(tmp_path, devs=[])
    (root / "Devs" / ".esengine.md.tmp").write_text("half a note", encoding="utf-8")
    devs.apply(devs.plan([rec(login="esengine")], [], optout=NO_ONE,
                         verdicts=VERDICTS), root)
    assert not list((root / "Devs").glob(".*.tmp"))


def test_deleting_a_note_that_is_already_gone_is_not_an_error(tmp_path):
    root = scratch_vault(tmp_path, devs=[])
    got = devs.CorpusPlan(deletes_consent=["never-existed"])
    assert devs.apply(got, root)["deleted"] == []


# --- write_corpus(): where the corpus lands --------------------------------------

def test_a_dry_run_lands_under_scratch_and_a_real_write_does_not(tmp_path):
    root = tmp_path / "vault"
    (root / "Devs").mkdir(parents=True)
    record = rec(login="esengine")
    _, out = devs.write_corpus([record], settings_for(root, dry_run=True),
                               optout=NO_ONE, verdicts=VERDICTS)
    assert (root / "_scratch" / "Devs" / "esengine.md").is_file()
    assert not (root / "Devs" / "esengine.md").exists()
    assert out["dry_run"] is True

    _, out = devs.write_corpus([rec(login="obra")], settings_for(root, dry_run=False),
                               optout=NO_ONE, verdicts=VERDICTS)
    assert (root / "Devs" / "obra.md").is_file()


def test_write_corpus_reconciles_against_what_is_already_in_scratch(tmp_path):
    root = tmp_path / "vault"
    scratch = root / "_scratch" / "Devs"
    scratch.mkdir(parents=True)
    (scratch / "gone.md").write_text(devs_note("gone"), encoding="utf-8")
    _, out = devs.write_corpus([rec(login="esengine")], settings_for(root),
                               optout=NO_ONE, verdicts=VERDICTS)
    assert out["deleted"] == ["gone"] and out["written"] == ["esengine"]
    assert out["plan"]["existing"] == 1


def test_existing_logins_is_empty_and_quiet_when_the_directory_is_absent(tmp_path):
    assert devs.existing_logins(tmp_path / "nowhere") == []


def test_a_dataclass_record_writes_the_same_bytes_as_its_dict(tmp_path):
    """The writer takes RECORDS, and they arrive both ways: off the producer as a
    DevRecord and out of a run json as a dict."""
    from cerebro.gitintel.devs_spike import DevRecord
    record = rec(login="esengine")
    as_dataclass = DevRecord(**record)
    root = tmp_path / "vault"
    root.mkdir()
    devs.apply(devs.plan([as_dataclass], [], optout=NO_ONE, verdicts=VERDICTS), root)
    assert (root / "Devs" / "esengine.md").read_text(encoding="utf-8") \
        == devs.render(record)


def test_the_vault_override_moves_where_the_corpus_is_WRITTEN_not_only_read(tmp_path):
    """The CLI's `--vault` exists because the Signals corpus is not in every checkout.
    If it moved only the READ, the corpus would land under the configured vault and the
    reconciliation would be computed against the wrong disk entirely — deleting notes
    that are not there and leaving the ones that are."""
    configured = tmp_path / "configured"
    elsewhere = tmp_path / "elsewhere"
    configured.mkdir()
    elsewhere.mkdir()
    devs.write_corpus([rec(login="esengine")], settings_for(configured, dry_run=True),
                      vault_path=elsewhere, optout=NO_ONE, verdicts=VERDICTS)
    assert (elsewhere / "_scratch" / "Devs" / "esengine.md").is_file()
    assert not (configured / "_scratch").exists()


# --- every number in a written note, recomputed independently -------------------
#
# THE CHARTER'S RULE IS THAT A WRONG NUMBER ABOUT A NAMED PERSON IS WORSE THAN NO PAGE.
# So this does not compare shapes and it does not compare the record against itself: it
# re-derives every window metric, the weekly series and every automation shape metric
# from the SAME parsed ClickHouse rows, through `gharchive`/`shape`/`facets` directly,
# and asserts EXACT equality against what the note on disk actually says.

def _cohort_run(tmp_path, logins):
    from cerebro.gitintel import devs_spike

    corpus = tmp_path / "vault" / "Signals"
    corpus.mkdir(parents=True)
    for i, login in enumerate(logins):
        (corpus / f"n{i}.md").write_text(
            f"---\nurl: https://github.com/{login}/proj\n"
            f"captured: 2026-0{i % 9 + 1}-01T00:00:00+00:00\n---\nbody\n",
            encoding="utf-8")
    verdicts = tmp_path / "verdicts.yaml"
    verdicts.write_text("denied: []\ncleared: []\n", encoding="utf-8")

    class _Client:
        def __init__(self):
            self._calls = 0
            self._cache_hits = 0

        def get_user(self, login):
            return {"login": login, "type": "User", "name": login}

        def request(self, path, params=None):
            return []

    text = (FIXTURES / "gharchive_cohort_90d.tsv").read_text(encoding="utf-8")
    _, _, records, _ = devs_spike.run(
        tmp_path / "vault", tmp_path / "out", client=_Client(),
        verdicts_path=str(verdicts), log=lambda *a: None,
        transport=lambda sql: text)
    return records, text


def test_every_number_in_every_written_note_is_recomputed_and_matches(tmp_path):
    """The recompute pass. Reads the notes on DISK, re-derives every number from the raw
    rows, and compares values rather than shapes."""
    import yaml

    from cerebro.gitintel import facets as facets_mod, gharchive, shape

    logins = ["simonw", "obra", "sindresorhus", "kentcdodds", "Rich-Harris",
              "paulmillr"]
    records, text = _cohort_run(tmp_path, logins)
    root = tmp_path / "vault"
    got = devs.plan(records, [], optout=NO_ONE, verdicts=denylist.EMPTY)
    devs.apply(got, root)
    notes = sorted((root / "Devs").glob("*.md"))
    assert notes, "no notes were written; every assertion below would be vacuous"

    # Independently re-parsed from the SAME rows, through the producer-side helpers
    # rather than through the record.
    truth = gharchive.pool_metrics(logins, windows=(7, 30, 90),
                                   transport=lambda sql: text)
    by_key = {k.lower(): v for k, v in truth.items()}

    for note in notes:
        body = note.read_text(encoding="utf-8")
        fm = yaml.safe_load(body[4:body.index("\n---\n")])
        m = by_key[fm["login"].lower()]
        for window, days in (("7d", 7), ("30d", 30), ("90d", 90)):
            w = fm["windows"][window]
            src = m[days]
            assert w["pushes"] == src.pushes, (note.name, window)
            assert w["distinct_repos"] == src.distinct_repos, (note.name, window)
            assert w["active_days"] == src.active_days, (note.name, window)
            assert w["repos_not_owned"] == src.repos_not_owned, (note.name, window)
            assert w["not_owned_basenames"] == src.not_owned_basenames, (note.name,)
            assert w["not_owned_owners"] == src.not_owned_owners, (note.name,)
            # The file must also agree with itself: a window cannot hold more active
            # days than it has days, which is the site's own build-killing assertion.
            assert w["active_days"] <= days, (note.name, window)
            assert fm["facets"][window] == facets_mod.window_facets(src), note.name

        m90 = m[90]
        a = fm["automation"]
        assert a["push_per_day"] == round(shape.push_per_active_day(m90), 4)
        assert a["not_owned_ratio"] == round(shape.not_owned_ratio(m90), 4)
        assert a["basename_concentration"] == round(
            shape.basename_concentration(m90), 4)
        assert a["repo_per_active_day"] == round(shape.repo_per_active_day(m90), 4)

        assert fm["pushes_per_week"] == list(m90.pushes_per_week)
        assert len(fm["pushes_per_week"]) == 13
        assert sum(fm["pushes_per_week"]) <= fm["windows"]["90d"]["pushes"]


def test_the_body_sentence_agrees_with_the_frontmatter_it_sits_under(tmp_path):
    """The one place a human reads a number in prose. A body that disagreed with its own
    frontmatter would be a wrong statement about a named person in the more readable of
    the two places."""
    import re

    import yaml

    records, _ = _cohort_run(tmp_path, ["simonw", "obra", "sindresorhus"])
    root = tmp_path / "vault"
    devs.apply(devs.plan(records, [], optout=NO_ONE, verdicts=denylist.EMPTY), root)
    for note in sorted((root / "Devs").glob("*.md")):
        text = note.read_text(encoding="utf-8")
        fm = yaml.safe_load(text[4:text.index("\n---\n")])
        body = text.split("\n---\n", 1)[1]
        # `[1]` is the sentence: the body is heading, blank, sentence, blank, url.
        sentence = body.split("\n\n")[1]
        numbers = [int(x) for x in re.findall(r"\b(\d+)\b", sentence)]
        w = fm["windows"]["90d"]
        assert numbers[:4] == [w["pushes"], w["distinct_repos"], w["active_days"], 90], \
            note.name
