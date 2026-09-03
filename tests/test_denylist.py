"""T09t — F017 quality verdicts file, both terminal states."""
from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.gitintel import denylist

SHIPPED = Path("config/devs_denylist.yaml")


def _write(tmp_path, text):
    p = tmp_path / "verdicts.yaml"
    p.write_text(text, encoding="utf-8")
    return p


GOOD = """
denied:
  - login: Someone
    verdict: automation
    shape: fork_farm
    evidence: "90d: 100 pushes / 20 repos / concentration 0.90"
    reviewed_by: owner
    reviewed_on: 2026-08-26
cleared:
  - login: Realdev
    verdict: human
    shape: fork_farm
    evidence: "90d: 50 pushes / 12 repos / concentration 0.70 — shared project prefix"
    reviewed_by: owner
    reviewed_on: 2026-08-26
"""


def test_the_shipped_denials_are_exactly_the_ones_a_review_recorded(tmp_path):
    """The denied section is the ONLY path to `excluded`, so its membership is pinned.

    `gcgh159` joined on 2026-08-27 from the e02 eyeball, not from any mechanical shape:
    489 pushes onto the single repo `GCGH159/green` across 88 of 90 days, a tree of
    auto-log.md/data.txt/stats.txt, templated four-per-batch commits one second apart.
    Every flag in `admission.flags()` passes it — push_per_active_day 5.56 is under the
    15 line, not_owned_ratio 0.0 cannot fire fork_farm, distinct_repos 1 cannot fire
    mass_self_repo. It is the live proof that the mechanical predicate is a floor and the
    eyeball is load-bearing, which is why criterion 4 says "verified by eye".
    """
    v = denylist.load(SHIPPED)
    assert sorted(v.denied) == ["dicklesworthstone", "diegosouzapw", "gcgh159"]


def test_no_shipped_verdict_claims_the_owner_signed_it(tmp_path):
    """NOTHING in this file may assert the owner's signature until the owner gives it.

    Two entries shipped stamped `reviewed_by: owner` on 2026-08-26, written by the
    building agent in the commit that created the file. The owner never saw them. A false
    signature is worse than a missing one: `OWNER_REVIEWERS` exists so a run can say whose
    eye, and `sanity_check` warns on every agent-recorded admission — two forged stamps
    silenced that warning for the only verdicts strong enough to exclude a person.
    """
    v = denylist.load(SHIPPED)
    forged = [e.login for d in (v.denied, v.cleared) for e in d.values()
              if denylist.is_owner_signed(e)]
    assert forged == [], (
        f"{len(forged)} verdict(s) claim an owner signature that was never given: "
        f"{forged}. An agent records `reviewed_by: <agent-name>`; only the owner's own "
        f"countersign may use a name in OWNER_REVIEWERS.")


def test_the_shipped_clearings_are_reviewed_and_carry_this_runs_numbers():
    """Every account worked off the F066 flag queue leaves a durable record. A verdict
    that lives only in a scratch file is not a verdict: nothing loads it, and the
    account is re-flagged identically on the next run."""
    v = denylist.load(SHIPPED)
    assert v.cleared, "the flag queue was worked; its clearings must be committed"
    for login, entry in v.cleared.items():
        assert entry.verdict == "human"
        assert entry.shape in {"fork_farm", "high_push_rate", "mass_self_repo",
                               "synthetic_repo"}
        assert "90d live" in entry.evidence
        assert "active days" in entry.evidence      # numeric evidence from the run
        assert len(entry.evidence) > 120, f"{login}: no human reason recorded"
        assert entry.reviewed_by and entry.reviewed_on


def test_no_login_is_both_denied_and_cleared_in_the_shipped_file():
    v = denylist.load(SHIPPED)
    assert not (set(v.denied) & set(v.cleared))


def test_the_shipped_denials_carry_regenerated_numeric_evidence():
    v = denylist.load(SHIPPED)
    for entry in v.denied.values():
        assert any(ch.isdigit() for ch in entry.evidence)
        assert "90d" in entry.evidence
        assert entry.reviewed_by and entry.reviewed_on
    assert v.denied["dicklesworthstone"].shape == "mass_self_repo"
    assert v.denied["diegosouzapw"].shape == "fork_farm"
    # the recorded drift: two live runs measured 2 not-owned basenames, not the
    # registry's 3, and the shipped evidence must carry the measurement
    assert "2 basenames" in v.denied["diegosouzapw"].evidence


def test_the_shipped_file_is_not_the_opt_out_list():
    text = SHIPPED.read_text(encoding="utf-8")
    assert "NOT THE OPT-OUT LIST" in text.upper()
    assert "consent" in text.lower()


def test_both_sections_load(tmp_path):
    v = denylist.load(_write(tmp_path, GOOD))
    assert sorted(v.denied) == ["someone"]
    assert sorted(v.cleared) == ["realdev"]


def test_lookup_is_case_insensitive_in_both_sections(tmp_path):
    v = denylist.load(_write(tmp_path, GOOD))
    assert "SOMEONE" in v and "RealDev" in v


@pytest.mark.parametrize("section", ["denied", "cleared"])
def test_a_bare_login_entry_is_rejected_in_either_section(tmp_path, section):
    p = _write(tmp_path, f"{section}:\n  - someone\n")
    with pytest.raises(ValueError, match="not an entry"):
        denylist.load(p)


@pytest.mark.parametrize("section", ["denied", "cleared"])
@pytest.mark.parametrize("field", denylist.REQUIRED_FIELDS)
def test_every_mandatory_field_is_enforced_in_either_section(tmp_path, section, field):
    row = {"login": "x", "verdict": "automation", "shape": "fork_farm",
           "evidence": "90d: numbers", "reviewed_by": "owner",
           "reviewed_on": "2026-08-26"}
    row.pop(field)
    body = "\n".join(f"    {k}: \"{v}\"" for k, v in row.items())
    p = _write(tmp_path, f"{section}:\n  - login: x\n{body}\n"
               if field != "login" else f"{section}:\n  -\n{body}\n")
    with pytest.raises(ValueError, match=field):
        denylist.load(p)


def test_a_login_in_both_sections_is_a_load_time_error(tmp_path):
    p = _write(tmp_path, GOOD.replace("login: Realdev", "login: someone"))
    with pytest.raises(ValueError, match="BOTH"):
        denylist.load(p)


def test_a_file_with_no_cleared_key_loads_backward_compatibly(tmp_path):
    p = _write(tmp_path, GOOD.split("cleared:")[0])
    v = denylist.load(p)
    assert v.cleared == {}
    assert sorted(v.denied) == ["someone"]


def test_a_missing_file_is_empty_verdicts_not_a_crash(tmp_path):
    v = denylist.load(tmp_path / "nope.yaml")
    assert v.denied == {} and v.cleared == {}


def test_a_non_list_section_is_rejected(tmp_path):
    p = _write(tmp_path, "denied:\n  someone: automation\n")
    with pytest.raises(ValueError, match="must be a list"):
        denylist.load(p)
