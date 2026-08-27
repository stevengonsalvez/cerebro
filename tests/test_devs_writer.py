"""The write gate and the reconciling writer.

THE WRITE GATE IS THE PUBLISH GATE. `cerebro-vault` is public, so a record written into
`Devs/` is published data about a named human whether or not a page renders from it.
Every assertion here is about what does NOT get written.
"""
from __future__ import annotations

import copy
import json
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
