"""F067, PIPELINE HALF — the launch-blocking opt-out gate, proved end to end.

ONE LOGIN, SIX INDEPENDENT ABSENCES, EVERY ONE ASSERTED OVER BYTES THAT REALLY EXIST.
Not over an in-memory object: over the `.sql` files written to disk, the run json,
`plan().writes`, and the `*.md` in the corpus directory. An in-memory assertion cannot
tell "the gate worked" from "the artifact was never produced".

AND SIX NEGATIVE CONTROLS. Every absence below would pass vacuously against a pipeline
that produced nothing at all, so each one is paired with the identical run against an
EMPTY consent file, where the same login must be PRESENT in the same place.

NO THRESHOLD IS OVERRIDDEN ANYWHERE IN THIS FILE. The scorer this programme replaced
shipped broken for six production runs because every admission test lowered the real
0.55 to 0.02, so nothing ever exercised the value that actually ran. This module runs
the real ones. `crackscan.fetch()` admits nobody at 0.55, which is exactly why the
`crackscan/considered` Signal is the interesting one: it is emitted for every candidate
merely LOOKED AT, and it reaches the vault through the existing pipeline.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from cerebro.gitintel import denylist, devs_spike, optout, pool
from cerebro.gitintel.cache import GitIntelCache
from cerebro.sink import devs as devs_sink
from cerebro.sources import crackscan

FIXTURE = Path(__file__).parent / "fixtures" / "gharchive_cohort_90d.tsv"

#: The person who asked to be removed. A login that really is in the ClickHouse cohort
#: fixture, so the run has real numbers for them and every absence is a removal rather
#: than an account that was never there.
GONE = "obra"
STAYS = "simonw"
COHORT = [STAYS, GONE, "sindresorhus", "kentcdodds", "Rich-Harris", "paulmillr"]


# --- harness ------------------------------------------------------------------

def optout_file(tmp_path, *logins) -> str:
    body = "logins: []\n" if not logins else "logins:\n" + "".join(
        f'  - login: "{x}"\n' for x in logins)
    p = tmp_path / "devs_optout.yaml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def verdicts_file(tmp_path, body="denied: []\ncleared: []\n") -> str:
    p = tmp_path / "verdicts.yaml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def signals_corpus(tmp_path, logins) -> Path:
    d = tmp_path / "vault" / "Signals"
    d.mkdir(parents=True, exist_ok=True)
    for i, login in enumerate(logins):
        (d / f"n{i}.md").write_text(
            f"---\nurl: https://github.com/{login}/proj\n"
            f"captured: 2026-0{i % 9 + 1}-01T00:00:00+00:00\n---\nbody\n",
            encoding="utf-8")
    return tmp_path / "vault"


class Client:
    """Resolves every owner to itself; serves no repos. No network."""

    def __init__(self, logins):
        self.logins = {x.lower(): x for x in logins}
        self.paths: list[str] = []
        self._calls = 0
        self._cache_hits = 0

    def get_user(self, login):
        real = self.logins.get((login or "").lower())
        return None if not real else {"login": real, "type": "User", "name": real,
                                      "public_repos": 5, "followers": 10,
                                      "created_at": "2015-01-01T00:00:00Z",
                                      "html_url": f"https://github.com/{real}"}

    def get_user_repos(self, login, limit=20):
        return []

    def request(self, path, params=None):
        self.paths.append(path)
        self._calls += 1
        return []


def devs_run(tmp_path, *, optout_path, verdicts_path=None, out="out"):
    vault = signals_corpus(tmp_path, COHORT)
    text = FIXTURE.read_text(encoding="utf-8")
    return vault, devs_spike.run(
        vault, tmp_path / out, client=Client(COHORT),
        verdicts_path=verdicts_path or verdicts_file(tmp_path),
        optout_path=optout_path, log=lambda *a: None,
        transport=lambda sql: text)


# --- absence 1: the Signals crackscan emits -----------------------------------

def crackscan_signals(tmp_path, monkeypatch, optout_path):
    """The REAL `fetch()`, at the REAL 0.55 threshold, with no roster on disk."""
    roster = tmp_path / "cracked_devs.yaml"
    roster.write_text("version: 1\nwiring:\n  enabled: true\ndevs: []\n",
                      encoding="utf-8")

    class _Cl(Client):
        rate_limit: dict = {}

        def __init__(self, logins):
            super().__init__(logins)
            # A REAL cache object: `cheap_score` records a snapshot through it, and a
            # `None` here makes the funnel bail before a single candidate is scored, so
            # the control would report "no leak" for the wrong reason entirely.
            self.cache = GitIntelCache(":memory:")

        def get_user_repos(self, login, limit=20):
            return [{"full_name": f"{login}/proj", "html_url": "u",
                     "pushed_at": "2026-06-30T00:00:00+00:00"}]

        def request(self, path, params=None):
            if path.endswith("/contributors"):
                owner = path[len("/repos/"):-len("/contributors")].split("/")[0]
                return [{"login": owner}]
            return []

    monkeypatch.setattr(crackscan, "GitHubClient",
                        lambda settings=None, token=None: _Cl(COHORT))
    return crackscan.fetch(
        {"seed_repos": [f"{x}/proj" for x in COHORT], "roster_path": str(roster),
         "optout_path": optout_path},
        types.SimpleNamespace(vault_path="", github={}))


def test_1_absent_from_every_signal_crackscan_emits(tmp_path, monkeypatch):
    out = crackscan_signals(tmp_path, monkeypatch, optout_file(tmp_path, GONE))
    blob = json.dumps([{"url": s.url, "title": s.title, "text": s.clean_text,
                        "tags": s.source_tags, "entities": s.entity_tags,
                        "meta": s.meta} for s in out])
    assert GONE not in blob


def test_1_control_the_same_login_IS_in_a_signal_without_the_file(tmp_path, monkeypatch):
    out = crackscan_signals(tmp_path, monkeypatch, optout_file(tmp_path))
    tagged = {(s.meta.get("login"), tuple(s.source_tags)) for s in out}
    assert any(login == GONE for login, _ in tagged), \
        "the control must show the leak the gate exists to stop"
    assert any("crackscan/considered" in tags for _, tags in tagged), \
        "and it is the CONSIDERED tag that leaks, not the admitted one"


# --- absence 2: the rendered ClickHouse query bytes ---------------------------

def test_2_absent_from_the_sql_bytes_written_to_disk(tmp_path):
    _, (_, _, _, paths) = devs_run(tmp_path, optout_path=optout_file(tmp_path, GONE))
    assert paths["sql"], "no query bytes were written; the assertion would be vacuous"
    for sql in paths["sql"]:
        assert GONE not in sql.read_text(encoding="utf-8")


def test_2_control_the_login_IS_in_the_sql_bytes_without_the_file(tmp_path):
    _, (_, _, _, paths) = devs_run(tmp_path, optout_path=optout_file(tmp_path))
    assert any(GONE in p.read_text(encoding="utf-8") for p in paths["sql"])


# --- absence 3: the run json --------------------------------------------------

def test_3_absent_from_the_run_json(tmp_path):
    _, (_, _, records, paths) = devs_run(tmp_path,
                                         optout_path=optout_file(tmp_path, GONE))
    assert GONE not in paths["json"].read_text(encoding="utf-8")
    assert GONE not in {r.login.lower() for r in records}
    assert STAYS in {r.login.lower() for r in records}


def test_3_control_the_login_IS_in_the_run_json_without_the_file(tmp_path):
    _, (_, _, records, paths) = devs_run(tmp_path, optout_path=optout_file(tmp_path))
    assert GONE in paths["json"].read_text(encoding="utf-8")
    assert GONE in {r.login.lower() for r in records}


# --- absence 4: the publish set and plan().writes ------------------------------

def test_4_absent_from_the_publish_set_and_from_plan_writes(tmp_path):
    _, (_, _, records, _) = devs_run(tmp_path, optout_path=optout_file(tmp_path, GONE))
    consent = optout.load(optout_file(tmp_path, GONE))
    got = devs_sink.plan(records, [], optout=consent, verdicts=denylist.EMPTY)
    assert GONE not in {devs_sink.slug(r.login) for r in got.writes}
    assert STAYS in {devs_sink.slug(r.login) for r in got.writes}


def test_4_control_the_login_IS_in_plan_writes_without_the_file(tmp_path):
    _, (_, _, records, _) = devs_run(tmp_path, optout_path=optout_file(tmp_path))
    got = devs_sink.plan(records, [], optout=optout.EMPTY, verdicts=denylist.EMPTY)
    assert GONE in {devs_sink.slug(r.login) for r in got.writes}


# --- absence 5: gone from disk ------------------------------------------------

def test_5_an_existing_note_is_deleted_from_disk(tmp_path):
    """THE ONE THAT MAKES THE OPT-OUT A REMOVAL RATHER THAN A FILTER. A note already in
    the corpus must be UNLINKED, or an append-only writer leaves the page live for ever
    and charter outcome 4 is unmet."""
    vault, (_, _, records, _) = devs_run(tmp_path,
                                         optout_path=optout_file(tmp_path, GONE))
    corpus = vault / "Devs"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / f"{GONE}.md").write_text("yesterday's page\n", encoding="utf-8")
    consent = optout.load(optout_file(tmp_path, GONE))
    got = devs_sink.plan(records, devs_sink.existing_logins(vault),
                         optout=consent, verdicts=denylist.EMPTY)
    assert got.deletes_consent == [GONE]
    devs_sink.apply(got, vault)
    assert not (corpus / f"{GONE}.md").exists()
    assert not any(GONE in p.read_text(encoding="utf-8")
                   for p in corpus.glob("*.md"))


def test_5_control_the_note_survives_without_the_file(tmp_path):
    vault, (_, _, records, _) = devs_run(tmp_path, optout_path=optout_file(tmp_path))
    corpus = vault / "Devs"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / f"{GONE}.md").write_text("yesterday's page\n", encoding="utf-8")
    got = devs_sink.plan(records, devs_sink.existing_logins(vault),
                         optout=optout.EMPTY, verdicts=denylist.EMPTY)
    assert got.deletes_consent == []
    devs_sink.apply(got, vault)
    assert (corpus / f"{GONE}.md").is_file()


def test_5_the_removal_happens_even_when_the_run_is_unhealthy(tmp_path):
    """Consent deletions are exempt from every guard. A person who asked to be removed
    must be removed even on a morning the lane half-failed."""
    vault, (_, _, records, _) = devs_run(tmp_path,
                                         optout_path=optout_file(tmp_path, GONE))
    corpus = vault / "Devs"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / f"{GONE}.md").write_text("yesterday's page\n", encoding="utf-8")
    consent = optout.load(optout_file(tmp_path, GONE))
    got = devs_sink.plan(records, devs_sink.existing_logins(vault),
                         optout=consent, verdicts=denylist.EMPTY, healthy=False)
    devs_sink.apply(got, vault)
    assert not (corpus / f"{GONE}.md").exists()


# --- absence 6: THE OTHER FILE. A recorded verdict, not a request. -------------
#
# The verdicts file is a DIFFERENT file with a different meaning, and the sixth absence
# is asserted over the REAL `config/devs_denylist.yaml` rather than a synthetic one, with
# the logins read out of it at test time. A verdict recorded tomorrow is covered the day
# it lands, without anybody remembering to widen a list here.

REAL_VERDICTS = denylist.load(denylist.DEFAULT_PATH)


def test_6_every_denied_login_in_the_shipped_file_is_absent_from_the_corpus(tmp_path):
    """Read from the file, never transcribed. Today that is Dicklesworthstone,
    diegosouzapw and GCGH159; tomorrow it is whatever a reviewer recorded."""
    assert REAL_VERDICTS.denied, "an empty verdicts file makes this vacuous"
    stale = json.loads((Path(__file__).parent / "fixtures"
                        / "devs_record_stale_denied.json").read_text(encoding="utf-8"))
    records = [stale] + [dict(stale, login=login) for login in REAL_VERDICTS.denied]
    got = devs_sink.plan(records, [], optout=optout.EMPTY, verdicts=REAL_VERDICTS)
    written = {devs_sink.slug(r["login"]) for r in got.writes}
    for login in REAL_VERDICTS.denied:
        assert devs_sink.slug(login) not in written

    root = tmp_path / "vault"
    root.mkdir()
    devs_sink.apply(got, root)
    on_disk = {p.stem.lower() for p in (root / "Devs").glob("*.md")} \
        if (root / "Devs").is_dir() else set()
    for login in REAL_VERDICTS.denied:
        assert devs_sink.slug(login) not in on_disk


def test_6_control_GCGH159_and_ONLY_he_can_be_the_control(tmp_path):
    """THE ASYMMETRY IS THE POINT AND IT IS MEASURED, NOT ASSUMED.

    Drop the verdicts file and `GCGH159`'s record still passes clauses 1-5 unaided —
    admitted, clear, rest_verified, provenance 1 — and lands in `writes`. That is the
    whole hole the sixth clause closes.

    The other two CANNOT play this role and this test must not pretend they can:
    `Dicklesworthstone` fires `mass_self_repo` and `diegosouzapw` fires `fork_farm`, so
    with an emptied verdicts file they fall to `flagged` and clause 2 withholds them
    anyway. That asymmetry IS the charter's lesson 2 restated — the mechanical predicate
    is a floor, not a gate — and `GCGH159` exists in the denylist precisely because NO
    shape fires on him.
    """
    stale = json.loads((Path(__file__).parent / "fixtures"
                        / "devs_record_stale_denied.json").read_text(encoding="utf-8"))
    assert stale["login"] == "GCGH159"
    assert stale["automation"]["shapes"] == [], \
        "no mechanical shape fires on him; that is why he is the only usable control"
    got = devs_sink.plan([stale], [], optout=optout.EMPTY, verdicts=denylist.EMPTY)
    assert [r["login"] for r in got.writes] == ["GCGH159"]


def test_6_the_denied_login_is_deleted_from_disk_and_not_re_written(tmp_path):
    """Without clause six the SAME run deletes him (a denied verdict is a consent-class
    delete, which fires always) and re-writes him from the same plan."""
    stale = json.loads((Path(__file__).parent / "fixtures"
                        / "devs_record_stale_denied.json").read_text(encoding="utf-8"))
    root = tmp_path / "vault"
    (root / "Devs").mkdir(parents=True)
    (root / "Devs" / "GCGH159.md").write_text("a page\n", encoding="utf-8")
    got = devs_sink.plan([stale], devs_sink.existing_logins(root),
                         optout=optout.EMPTY, verdicts=REAL_VERDICTS)
    assert got.deletes_consent == ["GCGH159"]
    result = devs_sink.apply(got, root)
    assert result["deleted"] == ["GCGH159"] and result["written"] == []
    assert not (root / "Devs" / "GCGH159.md").exists()


# --- the two files never merge, and the gate never fails open ------------------

def test_the_consent_file_and_the_verdicts_file_are_never_the_same_file():
    assert optout.DEFAULT_PATH != denylist.DEFAULT_PATH
    assert Path(optout.DEFAULT_PATH).is_file()
    assert Path(denylist.DEFAULT_PATH).is_file()


def test_a_malformed_consent_file_stops_the_devs_run_rather_than_publishing(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("logins:\n  - login: a\n   broken: [\n", encoding="utf-8")
    with pytest.raises(ValueError):
        devs_run(tmp_path, optout_path=str(bad))


def test_the_gate_matches_on_the_slug_not_the_spelling(tmp_path):
    """`@Obra`, `OBRA` and `obra` are one person, and a consent gate that only matches
    the casing the pool happened to produce is a gate that fails open on a typo."""
    _, (_, _, records, _) = devs_run(tmp_path,
                                     optout_path=optout_file(tmp_path, "@OBRA "))
    assert GONE not in {pool.slug(r.login) for r in records}
