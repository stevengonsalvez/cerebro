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


def test_the_shipped_file_loads_with_the_two_day_one_denials(tmp_path):
    v = denylist.load(SHIPPED)
    assert sorted(v.denied) == ["dicklesworthstone", "diegosouzapw"]


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
