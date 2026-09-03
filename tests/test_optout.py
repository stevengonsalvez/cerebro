"""F049 — the CONSENT loader, and the fail-closed rule that is its whole reason to exist.

The interesting assertions here are the ones about MALFORMED input. A consent list that
degrades to "nobody opted out" when it cannot be parsed is worse than no consent list at
all: it publishes a person who asked to be removed and reports a clean run while doing
it. So every malformed shape below RAISES, and the tests say so explicitly rather than
asserting an empty result.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cerebro.gitintel import denylist, optout, pool


def _write(tmp_path, text: str) -> str:
    p = tmp_path / "devs_optout.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


# --- the slug rule -----------------------------------------------------------

@pytest.mark.parametrize("written", ["someone", "SomeOne", "@someone", "  SOMEONE  ",
                                     "@SomeOne "])
def test_every_spelling_of_the_same_login_matches(tmp_path, written):
    """A person writing `@SimonW` into the file must remove `simonw` from the corpus.
    A consent gate that only matches the exact casing the pool happened to produce is a
    consent gate that fails open on a typo."""
    path = _write(tmp_path, f'logins:\n  - login: "{written}"\n')
    oo = optout.load(path)
    assert "someone" in oo
    assert "SOMEONE" in oo
    assert "@someone" in oo


def test_the_slug_rule_is_the_same_one_the_pool_uses(tmp_path):
    """Restated, not imported — see the module docstring for why. Pinned so the two
    cannot drift into disagreeing about who a login is."""
    for raw in ("simonw", "SimonW", "@SimonW", "  simonw ", "", "@", "Rich-Harris"):
        assert optout.slug(raw) == pool.slug(raw)


# --- the fail-closed rules ---------------------------------------------------

def test_a_missing_file_means_nobody_opted_out():
    """The day-one state, and the only absence that is allowed to be quiet."""
    assert optout.load("config/does-not-exist-anywhere.yaml") is optout.EMPTY
    assert not optout.load("config/does-not-exist-anywhere.yaml")


def test_an_empty_file_is_empty_not_an_error(tmp_path):
    assert len(optout.load(_write(tmp_path, ""))) == 0
    assert len(optout.load(_write(tmp_path, "logins: []\n"))) == 0


def test_unparseable_yaml_stops_the_run(tmp_path):
    """THE CENTRAL TEST. Not `== EMPTY`: an exception."""
    path = _write(tmp_path, "logins:\n  - login: a\n   bad indent: [\n")
    with pytest.raises(ValueError) as exc:
        optout.load(path)
    assert "STOPS the run" in str(exc.value)


def test_a_non_mapping_document_stops_the_run(tmp_path):
    with pytest.raises(ValueError, match="expected a mapping"):
        optout.load(_write(tmp_path, "- someone\n- someoneelse\n"))


def test_a_non_list_logins_key_stops_the_run(tmp_path):
    with pytest.raises(ValueError, match="must be a list"):
        optout.load(_write(tmp_path, "logins: someone\n"))


def test_an_entry_without_a_login_stops_the_run(tmp_path):
    with pytest.raises(ValueError, match="has no `login:`"):
        optout.load(_write(tmp_path, "logins:\n  - requested_on: 2026-09-01\n"))


def test_an_entry_with_an_empty_login_stops_the_run(tmp_path):
    with pytest.raises(ValueError, match="has no `login:`"):
        optout.load(_write(tmp_path, 'logins:\n  - login: "   "\n'))


def test_a_bare_string_entry_stops_the_run_and_says_what_the_shape_is(tmp_path):
    with pytest.raises(ValueError, match="bare string"):
        optout.load(_write(tmp_path, "logins:\n  - someone\n"))


@pytest.mark.parametrize("stray", optout.VERDICT_FIELDS)
def test_a_verdict_shaped_entry_is_rejected_and_names_the_other_file(tmp_path, stray):
    """The two files must not be confusable. An entry carrying a reviewer's vocabulary
    is somebody editing the wrong file, and the error says which one."""
    path = _write(tmp_path, f'logins:\n  - login: someone\n    {stray}: x\n')
    with pytest.raises(ValueError) as exc:
        optout.load(path)
    assert "devs_denylist.yaml" in str(exc.value)


# --- the shape of what comes back --------------------------------------------

def test_requested_on_is_recorded_for_the_operator_and_note_is_ignored(tmp_path):
    path = _write(tmp_path, 'logins:\n  - login: Someone\n'
                            '    requested_on: 2026-09-01\n'
                            '    note: "asked by email"\n')
    oo = optout.load(path)
    assert oo.requested_on == {"someone": "2026-09-01"}
    assert oo.logins == frozenset({"someone"})


def test_filter_logins_preserves_order_and_removes_every_casing(tmp_path):
    oo = optout.load(_write(tmp_path, "logins:\n  - login: bee\n"))
    assert optout.filter_logins(["Ay", "BEE", "cee", "bee"], oo) == ["Ay", "cee"]


def test_partition_counts_what_it_removed(tmp_path):
    """The gate's effect has to be COUNTABLE, or an artifact cannot tell a gate that ran
    from a gate that was never wired up."""
    oo = optout.load(_write(tmp_path, "logins:\n  - login: bee\n"))
    kept, removed = optout.partition(
        [{"login": "Ay"}, {"login": "Bee"}], key=lambda d: d["login"], optout=oo)
    assert [k["login"] for k in kept] == ["Ay"]
    assert [r["login"] for r in removed] == ["Bee"]


def test_the_empty_optout_removes_nobody():
    """Negative control: every assertion above would pass vacuously against a gate that
    removes everybody, and this is what rules that out."""
    kept, removed = optout.partition(["a", "b"], optout=optout.EMPTY)
    assert kept == ["a", "b"] and removed == []
    assert optout.filter_logins(["a", "b"], optout.EMPTY) == ["a", "b"]


# --- the two files never merge ------------------------------------------------

def _imports(path: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            out.add((node.module or "").lstrip("."))
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
    return out


def test_optout_does_not_import_denylist_and_denylist_does_not_import_optout():
    """CONSENT and QUALITY are two files, two loaders and two vocabularies. The absence
    of an import is the mechanism that keeps them from converging by accident."""
    assert "denylist" not in _imports("cerebro/gitintel/optout.py")
    assert "optout" not in _imports("cerebro/gitintel/denylist.py")


def test_the_two_modules_share_no_type():
    assert not (set(vars(optout)) & {"VerdictEntry", "Verdicts"})
    assert not (set(vars(denylist)) & {"OptOut"})
    assert optout.DEFAULT_PATH != denylist.DEFAULT_PATH


def test_the_shipped_consent_file_loads_and_is_empty():
    """The committed file is the one every run reads. It must parse, and on day one it
    must remove nobody."""
    oo = optout.load(optout.DEFAULT_PATH)
    assert len(oo) == 0


def test_the_shipped_consent_file_says_what_it_is_not():
    """The header is load-bearing: the next person to edit this file must not reach for
    it to record a quality judgement."""
    text = Path(optout.DEFAULT_PATH).read_text(encoding="utf-8")
    assert "devs_denylist.yaml" in text
    assert "CONSENT" in text
    for banned in ("hand-picked", "curated", "human-reviewed"):
        assert banned not in text.lower()
