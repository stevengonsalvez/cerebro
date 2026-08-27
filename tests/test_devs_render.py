"""F037 — the serialiser, proved by parsing what it emits.

THE ASSERTION THAT MATTERS IS THE ROUND TRIP, NOT THE SHAPE. A writer that emits
plausible-looking YAML which a parser reads back differently publishes a wrong number,
or a wrong login, about a named human, and every "does it contain the key" test in the
world passes while it does. So the central test here parses the frontmatter with a real
YAML parser and asserts the result EQUALS the record it started from.

The hostile record exists because the real corpus is one bad day from becoming it: two
publish-set logins are already all-digit strings, and a 16-hex provenance hash is
all-digit with probability about 1 in 1,845 per hash.
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
import yaml

from cerebro.gitintel.devs_spike import DevRecord
from cerebro.sink import devs

FIXTURES = Path(__file__).parent / "fixtures"
REC = json.loads((FIXTURES / "devs_schema_sample.json").read_text(encoding="utf-8"))
FANOUT_REC = json.loads(
    (FIXTURES / "devs_schema_fanout_sample.json").read_text(encoding="utf-8"))
GOLDEN = FIXTURES / "devs_note_golden.md"

# Transcribed from the SITE's lib/vault/devs.ts. `DEV_SNAKE` is the admitted whitelist
# and `DEV_CONSUMED` is the accepted-and-dropped list; the loader asserts the key set
# equals their union EXACTLY, at this level and at every nested level. A key on neither
# list is a build-killing throw over there, which is why it is transcribed here: this is
# the belt that ships whether or not node is available to run the real loader.
SITE_DEV_SNAKE = ["login", "name", "discovered_via", "discovered_via_all",
                  "provenance_repos", "admitted", "low_n", "repos_populated",
                  "generated_at", "provenance", "pushes_per_week", "windows",
                  "automation", "reasons", "repos"]
SITE_DEV_CONSUMED = ["facets"]
SITE_WINDOW_SNAKE = ["pushes", "distinct_repos", "active_days", "repos_not_owned",
                     "not_owned_basenames", "not_owned_owners"]
SITE_AUTOMATION_SNAKE = ["state", "push_per_day", "repo_per_active_day",
                         "not_owned_ratio", "basename_concentration", "shapes",
                         "shape_evidence", "cleared_by", "cleared_on", "prefilter"]
SITE_AUTOMATION_CONSUMED = ["fork_provenance"]
SITE_REPO_SNAKE = ["name", "title", "description", "language", "topics", "stars_fact",
                   "first_seen", "last_push"]


def frontmatter(text: str) -> dict:
    """Parse a rendered note's frontmatter the way gray-matter does: the block between
    the first two `---` fences, through a YAML parser, with nothing else touched."""
    assert text.startswith("---\n")
    body = text[4:]
    end = body.index("\n---\n")
    return yaml.safe_load(body[:end])


def hostile(**over) -> dict:
    """The real record, mutated into every YAML trap the corpus can produce."""
    rec = copy.deepcopy(REC)
    rec.update(over)
    return rec


# --- the round trip ----------------------------------------------------------

@pytest.mark.parametrize("rec", [REC, FANOUT_REC], ids=["vault", "fanout"])
def test_a_real_record_round_trips_through_a_yaml_parser_exactly(rec):
    """Not "parses". EQUALS. Every int an int, every float the same float, every string
    still a string."""
    assert frontmatter(devs.render(rec)) == rec


def test_the_types_that_yaml_would_have_coerced_survive():
    back = frontmatter(devs.render(REC))
    assert isinstance(back["login"], str)
    assert isinstance(back["generated_at"], str), \
        "an unquoted ISO timestamp becomes a Date in gray-matter"
    assert isinstance(back["automation"]["cleared_on"], str)
    assert all(isinstance(h, str) for h in back["provenance"])
    assert set(back["windows"]) == {"7d", "30d", "90d"}
    assert all(isinstance(k, str) for k in back["windows"])
    assert all(isinstance(v, int) for v in back["pushes_per_week"])


@pytest.mark.parametrize("login", ["no", "on", "y", "NO", "0123456", "245678000000",
                                   "1105623876", "true", "off"])
def test_a_login_yaml_would_reinterpret_comes_back_as_the_same_string(login):
    """`no`/`on`/`y` are YAML 1.1 booleans, and two all-digit logins are in today's real
    publish set. The site derives the login from the FILENAME and throws when
    `String(data.login)` disagrees, so a coerced login is a build failure, not a typo."""
    back = frontmatter(devs.render(hostile(login=login)))
    assert back["login"] == login and isinstance(back["login"], str)


def test_an_all_digit_provenance_hash_comes_back_a_string():
    """LATENT, NOT PRESENT: none of today's 236 distinct hashes is all-digit, and one
    will be, eventually. The site's `asStrings()` throws the day it happens."""
    back = frontmatter(devs.render(hostile(provenance=["1234567890123456"])))
    assert back["provenance"] == ["1234567890123456"]
    assert isinstance(back["provenance"][0], str)


def test_a_repo_description_full_of_yaml_metacharacters_is_inert():
    rec = hostile(repos_populated=True, repos=[{
        "name": "weird-repo",
        "title": "weird-repo",
        "description": 'he said "hi": then\n---\nnot a new document \\ either',
        "language": None,
        "topics": ["true", "null", "on", "1.0"],
        "stars_fact": 0,
        "first_seen": None,
        "last_push": "2026-08-01",
    }])
    back = frontmatter(devs.render(rec))
    repo = back["repos"][0]
    # The newline is collapsed to a space by the emitter; everything else survives.
    assert repo["description"] == 'he said "hi": then --- not a new document \\ either'
    assert repo["topics"] == ["true", "null", "on", "1.0"]
    assert all(isinstance(t, str) for t in repo["topics"])
    assert repo["language"] is None and repo["first_seen"] is None


def test_a_null_name_stays_null_and_an_empty_name_stays_an_empty_string():
    assert frontmatter(devs.render(hostile(name=None)))["name"] is None
    assert frontmatter(devs.render(hostile(name="")))["name"] == ""


def test_a_float_never_reaches_yaml_in_exponent_form():
    """`repr(1e-05)` is `1e-05`, which js-yaml hands over as the STRING "1e-05" and the
    site's `asFloat` throws on. Fixed-point is the only safe form."""
    rec = hostile()
    rec["automation"] = dict(rec["automation"], push_per_day=0.00001,
                             not_owned_ratio=1234.56785)
    text = devs.render(rec)
    assert "e-05" not in text and "e+" not in text
    back = frontmatter(text)
    assert isinstance(back["automation"]["push_per_day"], float)
    assert back["automation"]["not_owned_ratio"] == round(1234.56785, 4)


def test_booleans_render_as_yaml_booleans_and_not_as_ones_and_zeroes():
    back = frontmatter(devs.render(hostile(admitted=True, low_n=False)))
    assert back["admitted"] is True and back["low_n"] is False


# --- the contract with the site ------------------------------------------------

def test_the_serialiser_key_set_is_exactly_the_producer_record():
    """Producer and serialiser cannot drift: a field added to `DevRecord` without a slot
    here would silently vanish from every published note."""
    assert set(devs.FRONTMATTER_KEYS) == set(DevRecord.__dataclass_fields__)
    assert len(devs.FRONTMATTER_KEYS) == len(set(devs.FRONTMATTER_KEYS)) == 16


def test_the_emitted_key_set_is_exactly_what_the_site_admits_plus_what_it_consumes():
    back = frontmatter(devs.render(REC))
    assert sorted(back) == sorted(SITE_DEV_SNAKE + SITE_DEV_CONSUMED)
    for window in ("7d", "30d", "90d"):
        assert sorted(back["windows"][window]) == sorted(SITE_WINDOW_SNAKE)
    assert sorted(back["automation"]) == sorted(
        SITE_AUTOMATION_SNAKE + SITE_AUTOMATION_CONSUMED)


def test_every_repo_element_carries_exactly_the_frozen_repo_keys():
    rec = hostile(repos_populated=True, repos=[{
        "name": "llm", "title": "llm", "description": "a CLI", "language": "Python",
        "topics": ["llm"], "stars_fact": 1, "first_seen": "2026-01-01",
        "last_push": "2026-08-01"}])
    repo = frontmatter(devs.render(rec))["repos"][0]
    assert sorted(repo) == sorted(SITE_REPO_SNAKE)


def test_a_record_missing_a_frozen_field_raises_rather_than_emitting_a_hole():
    rec = hostile()
    del rec["facets"]
    with pytest.raises(ValueError, match="missing frozen field"):
        devs.render(rec)


def test_a_record_carrying_an_unfrozen_field_raises_here_not_at_the_site_build():
    """The site asserts an exact key set and turns an additive producer field into a
    build-killing throw. Catching it at the emitter names the field and the remedy."""
    with pytest.raises(ValueError, match="unfrozen field"):
        devs.render(hostile(surprise=1))


# --- determinism ---------------------------------------------------------------

def test_the_golden_note_is_byte_identical():
    """A rendering change must be visible as a diff in a committed file, not discovered
    when 1,300 notes rewrite themselves in the public vault."""
    assert devs.render(REC) == GOLDEN.read_text(encoding="utf-8")


def test_rendering_is_independent_of_the_input_dict_ordering():
    """The same record arrives two ways: off the producer in construction order, and out
    of a `sort_keys=True` run json in alphabetical order. If those rendered differently,
    every `apply()` comparison would report a spurious change and the vault would take a
    full-corpus commit for nothing."""
    def reorder(o):
        if isinstance(o, dict):
            return {k: reorder(o[k]) for k in reversed(list(o))}
        if isinstance(o, list):
            return [reorder(x) for x in o]
        return o
    assert devs.render(reorder(REC)) == devs.render(REC)


def test_the_timestamp_elided_form_differs_only_in_the_timestamp():
    """1.6: `generated_at` means "when these facts last changed", and the comparison
    that makes that true is this one."""
    a = devs.render(REC)
    b = devs.render(dict(REC, generated_at="2099-01-01T00:00:00+00:00"))
    assert a != b
    assert devs.render(REC, timestamp=False) == devs.render(
        dict(REC, generated_at="2099-01-01T00:00:00+00:00"), timestamp=False)
    assert 'generated_at: ""' in devs.render(REC, timestamp=False)


# --- what the body may and may not say -----------------------------------------

def test_the_body_states_the_ninety_day_numbers_and_judges_nobody():
    body = devs.render(REC).split("\n---\n", 1)[1]
    w = REC["windows"]["90d"]
    assert f"# {REC['login']}" in body
    assert (f"{w['pushes']} pushes across {w['distinct_repos']} repositories on "
            f"{w['active_days']} active days in the last 90 days") in body
    low = body.lower()
    for banned in ("cracked", "elite", "prolific", "best", "top ", "hand-picked",
                   "curated", "human-reviewed", "score", "rank"):
        assert banned not in low, f"the body must not say {banned!r} about a person"


def test_the_body_is_singular_when_the_numbers_are():
    rec = copy.deepcopy(REC)
    rec["windows"]["90d"].update(pushes=1, distinct_repos=1, active_days=1)
    body = devs.render(rec).split("\n---\n", 1)[1]
    assert "1 push across 1 repository on 1 active day in the last 90 days" in body


# --- the condemned writer is not reused ------------------------------------------

def test_the_devs_sink_never_imports_the_condemned_developer_writer():
    """Charter: rebuilt, not patched. `sink/entities.py::developer_markdown` is the
    follower/star model, duck-typed over exactly the fields e02 removed."""
    imported = set()
    src = Path("cerebro/sink/devs.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").lstrip("."))
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    assert "entities" not in imported
    assert "crackscore" not in imported
    # The NAME must not be reachable as code. It appears in the module docstring, which
    # is where the reason it is not reused is recorded, so the check is over identifiers
    # rather than over the source text.
    named = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    named |= {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
    assert "developer_markdown" not in named
