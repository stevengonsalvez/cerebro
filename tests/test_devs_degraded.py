"""A DEGRADED RUN MUST NOT UNPUBLISH ANYBODY, AND MUST NOT DO IT QUIETLY.

The defect this file pins, reproduced live before it was fixed: re-running
`devs-refresh --dry-run` against the real 1,036-note corpus with no token logged 273
`resolve failed for ... GitHub 403 ... API rate limit exceeded` lines, published 31 of
1,316 people, and printed `"healthy": true`. Every term in the old `healthy` conjunction
stayed clean, and each one for a structural reason rather than by luck:

    result.ok                the sanity gate reads the top 20, and 31 people still
                             produce a clean top 20
    budget.truncated         set only when the paid pre-filter EXHAUSTS its cap. A 403
                             is a call that was made and refused, so nothing truncated
    clickhouse_scans == 3    the free lane needs no token and is unaffected
    bool(records)            31 records is non-empty

Only the churn cap — `max(25, 25% of corpus)` — stood between that run and deleting
1,285 real people's notes, and a MODERATE degradation slips under the cap entirely. The
fix is a fourth term: REST calls that RAISED are counted at the client and any non-zero
count makes the run untrustworthy, because every consumer in this lane swallows its own
exceptions so one bad account cannot sink the run.

The second half is that a refused run PAGES. `sink/devs.py` promises the churn cap
"returns a loud reason the pipeline stage turns into a page"; before the fix that reason
went into a summary printed on the way to exit 0, and `run.sh` pages only on a non-zero
exit. Same failure shape as the roundup's (commit ebe7c08), same remedy.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cerebro import config
from cerebro.__main__ import main
from cerebro.gitintel import devs_spike
from cerebro.gitintel import gharchive as _gharchive
from cerebro.gitintel.cache import GitIntelCache
from cerebro.sink import devs as devs_sink

FIXTURE = Path(__file__).parent / "fixtures" / "gharchive_cohort_90d.tsv"
HUMANS = ["simonw", "obra", "sindresorhus", "kentcdodds", "Rich-Harris", "paulmillr"]

#: Everybody except this one 403s on the degraded run. FIVE of six disappear, which is
#: UNDER the churn cap of `max(25, 25% of 6)` = 25 — the exact "moderate degradation
#: slips under the cap" case the absolute cap cannot catch.
SURVIVOR = "simonw"


class DegradableClient:
    """A `GitHubClient` stand-in with the real one's three counters.

    `_errors` is incremented on the raise and never on the return, exactly as
    `GitHubClient.request()` does it — `tests/test_github_client.py` pins that the real
    client keeps this contract, so this fake cannot drift into testing itself.
    """

    def __init__(self, logins, failing=(), cache=None):
        self.logins = {x.lower(): x for x in logins}
        self.failing = {x.lower() for x in failing}
        self._calls = 0
        self._cache_hits = 0
        self._errors = 0
        # F057's history store. Present only where a cell needs `last_good_at` to be a
        # real date read back out of a real sqlite file.
        if cache is not None:
            self.cache = cache

    def _maybe_fail(self, who: str):
        if (who or "").lower() in self.failing:
            self._errors += 1
            raise RuntimeError(
                f"GitHub 403 for /users/{who}: API rate limit exceeded")

    def get_user(self, login):
        self._calls += 1
        self._maybe_fail(login)
        real = self.logins.get((login or "").lower())
        return None if not real else {"login": real, "type": "User", "name": real}

    def request(self, path, params=None):
        self._calls += 1
        return []


def corpus(tmp_path, logins) -> Path:
    d = tmp_path / "vault" / "Signals"
    d.mkdir(parents=True, exist_ok=True)
    for i, login in enumerate(logins):
        (d / f"n{i}.md").write_text(
            f"---\nurl: https://github.com/{login}/proj\n"
            f"captured: 2026-0{i % 9 + 1}-01T00:00:00+00:00\n---\nbody\n",
            encoding="utf-8")
    return tmp_path / "vault"


_REAL_POOL_METRICS = _gharchive.pool_metrics


def _fake_pool_metrics(logins, windows=(7, 30, 90), transport=None, **kw):
    text = FIXTURE.read_text(encoding="utf-8")
    return _REAL_POOL_METRICS(logins, windows=windows, transport=lambda sql: text)


@pytest.fixture
def stage(tmp_path, monkeypatch, capsys):
    """The real `main()` over a real writer, with the client swappable per run."""
    vault = corpus(tmp_path, HUMANS)
    settings = SimpleNamespace(vault_path=vault, dry_run=True, sources={},
                               github={"cache_path": ":memory:"}, ntfy_topic="t")
    monkeypatch.setattr(config, "load", lambda **kw: settings)
    import cerebro.__main__ as main_mod
    monkeypatch.setattr(main_mod, "load", lambda **kw: settings, raising=False)
    monkeypatch.setattr("cerebro.gitintel.gharchive.pool_metrics", _fake_pool_metrics)
    monkeypatch.setattr(devs_spike.gharchive, "pool_metrics", _fake_pool_metrics)

    box = SimpleNamespace(tmp_path=tmp_path, vault=vault, settings=settings,
                          capsys=capsys, client=None, pages=[], monkeypatch=monkeypatch)

    def use(client):
        box.client = client
        monkeypatch.setattr(
            "cerebro.gitintel.github_client.GitHubClient",
            lambda settings=None, token=None, cache=None: client)

    from cerebro.sink import notify
    monkeypatch.setattr(notify, "push_failure",
                        lambda msg, s: box.pages.append(msg))

    box.use = use
    return box


def _corpus_root(stage) -> Path:
    return stage.vault / "_scratch" / "Devs" if stage.settings.dry_run \
        else stage.vault / "Devs"


def _files(stage) -> set[str]:
    root = _corpus_root(stage)
    return {p.stem for p in root.glob("*.md")} if root.is_dir() else set()


def _hashes(stage) -> dict[str, str]:
    """`{filename: sha256}` over the sandbox corpus. THE ONLY PLACE THIS CAN BE ASSERTED.

    The harness writes to `tmp_path/vault/_scratch/Devs`, which is the only path a run
    inside this suite can touch. A shell `find | shasum` over a repo-root `_scratch/`
    hashes an empty set against an empty set and can never fail — the previous shape of
    this gate, and exactly the class of hollow proof the charter's fourth lesson names.
    """
    root = _corpus_root(stage)
    if not root.is_dir():
        return {}
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.glob("*.md"))}


def _record_identity(label: str, before: dict, after: dict) -> None:
    """Append both maps and their difference to the V7 evidence file, if one is asked for.

    THE EVIDENCE IS WRITTEN BY THE ASSERTION, so an empty difference in the file is proof
    the comparison ran rather than proof that nothing was looked at. An absent or empty
    file is a FAILED gate.
    """
    target = os.environ.get("E06_IDENTITY_LOG")
    if not target:
        return
    changed = sorted(set(before) ^ set(after)) + sorted(
        k for k in set(before) & set(after) if before[k] != after[k])
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"## {label}\n")
        fh.write(f"hashed_before: {len(before)}\n")
        fh.write(f"hashed_after: {len(after)}\n")
        for name in sorted(before):
            fh.write(f"  before {name} {before[name]}\n")
        for name in sorted(after):
            fh.write(f"  after  {name} {after[name]}\n")
        fh.write(f"DIFF: {'none' if not changed else ', '.join(changed)}\n\n")


def assert_corpus_identical(stage, before: dict, *, label: str,
                            except_keys=frozenset()) -> dict:
    """The byte-identity assertion, and the one-key-difference form the consent cell needs.

    Named files in the message, never "the corpora differ": a failure has to say WHICH
    note about WHICH named person moved.
    """
    after = _hashes(stage)
    _record_identity(label, before, after)
    expected = {k: v for k, v in before.items() if k not in except_keys}
    moved = sorted(set(expected) ^ set(after)) + sorted(
        k for k in set(expected) & set(after) if expected[k] != after[k])
    assert not moved, f"{label}: a degraded run moved {moved}"
    return after


def run_cli(stage, *argv) -> dict:
    optout = stage.tmp_path / "devs_optout.yaml"
    optout.write_text("logins: []\n", encoding="utf-8")
    verdicts = stage.tmp_path / "verdicts.yaml"
    verdicts.write_text("denied: []\ncleared: []\n", encoding="utf-8")
    old = sys.argv
    sys.argv = ["cerebro", "devs-refresh", "--vault", str(stage.vault),
                "--out", str(stage.tmp_path / "out"),
                "--optout", str(optout), "--verdicts", str(verdicts), *argv]
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise AssertionError(f"stage exited {exc.code}")
    finally:
        sys.argv = old
    text = stage.capsys.readouterr().out
    return json.loads(text[text.index("{"):])


# --- the reproduction ----------------------------------------------------------

def test_a_healthy_run_publishes_and_is_the_control(stage):
    """Without this, every assertion below would pass against a stage that never wrote."""
    stage.use(DegradableClient(HUMANS))
    out = run_cli(stage, "--dry-run")
    assert out["healthy"] is True
    assert out["rest_failures"] == 0
    assert out["refused_reason"] == ""
    assert len(_files(stage)) == out["published"] > 1


def test_a_rate_limited_run_is_not_healthy_and_deletes_nobody(stage):
    """THE WHOLE FINDING, END TO END. A run whose REST lane 403s publishes a fraction of
    the corpus; the notes for everybody it could not resolve stay on disk untouched."""
    stage.use(DegradableClient(HUMANS))
    before = _files(stage) or (run_cli(stage, "--dry-run") and _files(stage))
    assert len(before) > 1

    degraded = [x for x in HUMANS if x != SURVIVOR]
    stage.use(DegradableClient(HUMANS, failing=degraded))
    out = run_cli(stage, "--dry-run")

    assert out["rest_failures"] > 0, "the 403s were counted nowhere"
    assert out["healthy"] is False, \
        "a run that could not resolve anybody reported a clean bill of health"
    assert out["published"] < len(before), "the reproduction did not actually degrade"
    assert out["deleted_churn"] == 0
    assert out["refused_reason"] == devs_sink.REFUSED_UNHEALTHY
    assert _files(stage) == before, "a degraded run unpublished real people"


def test_the_shrink_is_under_the_absolute_churn_cap_so_only_health_saves_it(stage):
    """The cap is `max(25, 25%)`; this corpus is six people, so five vanishing is well
    under it. Without the health term the churn rule would have executed every one of
    those deletions — which is why the fix is a health term and not a smaller cap."""
    stage.use(DegradableClient(HUMANS))
    run_cli(stage, "--dry-run")
    before = _files(stage)
    lost = len(before) - 1
    assert 0 < lost <= devs_sink.churn_cap(len(before))


def test_the_withheld_report_names_the_degradation(stage, tmp_path):
    stage.use(DegradableClient(HUMANS, failing=[x for x in HUMANS if x != SURVIVOR]))
    out = run_cli(stage, "--dry-run")
    body = Path(out["withheld_report"]).read_text(encoding="utf-8")
    assert "DEGRADED" in body and "churn deletions refused" in body


# --- the page ------------------------------------------------------------------

def test_a_degraded_live_run_pages_the_phone(stage):
    """`run.sh` pages only on a non-zero exit and this stage exits 0 by design, so the
    stage has to raise the alarm itself or a frozen corpus is silent for ever."""
    stage.settings.dry_run = False
    stage.use(DegradableClient(HUMANS))
    run_cli(stage)                        # seed a corpus at the real path
    assert stage.pages == []

    stage.use(DegradableClient(HUMANS, failing=[x for x in HUMANS if x != SURVIVOR]))
    out = run_cli(stage)
    assert out["healthy"] is False
    assert len(stage.pages) == 1
    page = stage.pages[0]
    assert devs_sink.REFUSED_UNHEALTHY in page
    assert "healthy=False" in page and "rest_failures=" in page


def test_a_healthy_live_run_never_pages(stage):
    """A page that fires on a good morning is a page an operator mutes."""
    stage.settings.dry_run = False
    stage.use(DegradableClient(HUMANS))
    out = run_cli(stage)
    assert out["healthy"] is True and stage.pages == []


def test_a_dry_run_never_pages(stage):
    """Every dev checkout and every test runs this stage dry."""
    stage.use(DegradableClient(HUMANS, failing=[x for x in HUMANS if x != SURVIVOR]))
    out = run_cli(stage, "--dry-run")
    assert out["healthy"] is False and stage.pages == []


def test_alerting_never_becomes_the_failure(stage, monkeypatch):
    """Best-effort, like every other alert path in this repo."""
    from cerebro.sink import notify

    def explode(*a, **k):
        raise OSError("curl: command not found")
    monkeypatch.setattr(notify, "push_failure", explode)
    stage.settings.dry_run = False
    stage.use(DegradableClient(HUMANS, failing=[x for x in HUMANS if x != SURVIVOR]))
    out = run_cli(stage)                  # must not raise
    assert out["healthy"] is False


# --- F058: the induced outage. The corpus does not move ------------------------
#
# EVERY CELL BELOW INDUCES A REAL FAILURE THROUGH THE REAL `pool_metrics`, RETRY LADDER
# INCLUDED. The charter's fourth measured lesson is that a degraded run looked healthy;
# a meter that has never been watched going red is not a meter. The byte-identity
# assertion lives HERE, inside the harness, over the `tmp_path` sandbox that is the only
# corpus this suite can actually move.

def _outage_metrics(exc, recorder):
    """Real `pool_metrics`, real ladder, a transport that always raises."""
    def boom(sql):
        raise exc
    def run(logins, windows=(7, 30, 90), transport=None, **kw):
        return _REAL_POOL_METRICS(logins, windows=windows, transport=boom,
                                  sleep=recorder.append)
    return run


def _drift_metrics(recorder):
    """Real `pool_metrics` against a result header that lost a column."""
    body = ("actor_login\tpushes\tdistinct_repos\tactive_days\trepos_not_owned\t"
            "not_owned_basenames\tmax_basename_group\tweeks_map\n"
            "simonw\t1\t1\t1\t0\t0\t1\t([0],[1])\n")
    def run(logins, windows=(7, 30, 90), transport=None, **kw):
        return _REAL_POOL_METRICS(logins, windows=windows, transport=lambda sql: body,
                                  sleep=recorder.append)
    return run


def _induce(stage, metrics_fn):
    stage.monkeypatch.setattr("cerebro.gitintel.gharchive.pool_metrics", metrics_fn)
    stage.monkeypatch.setattr(devs_spike.gharchive, "pool_metrics", metrics_fn)


def _healthy_corpus(stage, cache=None):
    """Seed a real corpus through the real writer, and return its hash map."""
    stage.use(DegradableClient(HUMANS, cache=cache))
    out = run_cli(stage, *([] if not stage.settings.dry_run else ["--dry-run"]))
    assert out["healthy"] is True and out["published"] > 1
    return _hashes(stage)


def test_an_unreachable_endpoint_leaves_the_corpus_byte_identical(stage, tmp_path):
    """THE GATE. Not "the same files": the same BYTES, named file by file."""
    cache = GitIntelCache(tmp_path / "gitintel.sqlite")
    before = _healthy_corpus(stage, cache=cache)
    assert len(before) > 1

    slept: list[float] = []
    _induce(stage, _outage_metrics(ConnectionError("connection refused"), slept))
    stage.use(DegradableClient(HUMANS, cache=cache))
    out = run_cli(stage, "--dry-run")

    assert out["healthy"] is False
    assert out["degraded"] == "unreachable"
    assert out["written"] == 0 and out["deleted_churn"] == 0
    assert_corpus_identical(stage, before, label="unreachable")
    assert slept == list(gharchive_ladder()), \
        "the transport ladder did not run, or a quota wait was used instead"


def test_the_degraded_artifact_dates_itself_from_the_snapshot_table(stage, tmp_path):
    """`last_good_at` is how an operator tells "ClickHouse died this morning" from "this
    stage has been dead for nine days". Read back independently with sqlite3."""
    import sqlite3

    cache_path = tmp_path / "gitintel.sqlite"
    cache = GitIntelCache(cache_path)
    _healthy_corpus(stage, cache=cache)

    _induce(stage, _outage_metrics(ConnectionError("down"), []))
    stage.use(DegradableClient(HUMANS, cache=cache))
    out = run_cli(stage, "--dry-run")

    db = sqlite3.connect(str(cache_path))
    newest = db.execute("SELECT max(captured_at) FROM push_window_snapshots").fetchone()[0]
    db.close()
    assert newest, "the healthy run recorded no history to degrade against"
    assert out["last_good_at"] == newest

    body = Path(out["degraded_report"]).read_text(encoding="utf-8")
    assert newest in body
    assert "No note was written and no note was deleted" in body
    assert "FROZEN" in body


def test_contract_drift_is_a_different_page_and_never_sleeps(stage, tmp_path):
    """Down and changed reach the operator as different words. The drift path also
    consumes no retry: today's ladder is [30, 60, 120] and no amount of waiting fixes a
    query that no longer matches the table."""
    cache = GitIntelCache(tmp_path / "gitintel.sqlite")
    stage.settings.dry_run = False
    before = _healthy_corpus(stage, cache=cache)
    stage.pages.clear()

    slept: list[float] = []
    _induce(stage, _drift_metrics(slept))
    stage.use(DegradableClient(HUMANS, cache=cache))
    out = run_cli(stage)

    assert out["degraded"] == "contract"
    assert slept == [], "drift consumed a retry"
    assert_corpus_identical(stage, before, label="contract-drift")
    assert len(stage.pages) == 1
    assert "CONTRACT DRIFT" in stage.pages[0]
    assert "UNREACHABLE" not in stage.pages[0]


def test_an_unreachable_endpoint_pages_once_with_the_other_text(stage, tmp_path):
    cache = GitIntelCache(tmp_path / "gitintel.sqlite")
    stage.settings.dry_run = False
    _healthy_corpus(stage, cache=cache)
    stage.pages.clear()

    _induce(stage, _outage_metrics(ConnectionError("refused"), []))
    stage.use(DegradableClient(HUMANS, cache=cache))
    out = run_cli(stage)

    assert out["degraded"] == "unreachable"
    assert len(stage.pages) == 1
    assert "UNREACHABLE" in stage.pages[0]
    assert "FROZEN" in stage.pages[0]


def test_a_degraded_dry_run_pages_nobody(stage):
    _induce(stage, _outage_metrics(ConnectionError("refused"), []))
    stage.use(DegradableClient(HUMANS))
    out = run_cli(stage, "--dry-run")
    assert out["healthy"] is False and stage.pages == []


def test_a_consent_deletion_still_runs_on_a_degraded_day_and_nobody_else_moves(
        stage, tmp_path):
    """CONSENT NEVER WAITS FOR AN UPSTREAM. The sha256 map differs by EXACTLY the opted-out
    key — asserted as one key, never as "the diff is non-empty", which a corpus-wide
    deletion would also satisfy."""
    cache = GitIntelCache(tmp_path / "gitintel.sqlite")
    before = _healthy_corpus(stage, cache=cache)
    gone = SURVIVOR
    assert f"{gone}.md" in before

    optout = stage.tmp_path / "consent-degraded.yaml"
    optout.write_text(
        f"logins:\n  - login: {gone}\n    requested_on: 2026-08-27\n", encoding="utf-8")

    _induce(stage, _outage_metrics(ConnectionError("refused"), []))
    stage.use(DegradableClient(HUMANS, cache=cache))
    out = run_cli(stage, "--dry-run", "--optout", str(optout))

    assert out["degraded"] == "unreachable"
    assert out["deleted_consent"] == 1
    assert out["deleted_churn"] == 0
    after = assert_corpus_identical(stage, before, label="consent-on-a-degraded-day",
                                    except_keys={f"{gone}.md"})
    assert set(before) - set(after) == {f"{gone}.md"}, \
        "exactly one note must have gone, and it must be the one that asked to"


def test_the_dateline_every_reader_sees_stops_advancing_and_does_not_move(
        stage, tmp_path):
    """V8's mechanism, proven here rather than only in a shell grep: `generated_at` is
    what the site renders as the profile dateline, and on a degraded day every note keeps
    the value the last healthy run wrote."""
    cache = GitIntelCache(tmp_path / "gitintel.sqlite")
    _healthy_corpus(stage, cache=cache)
    root = _corpus_root(stage)
    before = {p.name: _generated_at(p) for p in sorted(root.glob("*.md"))}
    assert before and all(before.values())

    _induce(stage, _outage_metrics(ConnectionError("refused"), []))
    stage.use(DegradableClient(HUMANS, cache=cache))
    run_cli(stage, "--dry-run")

    after = {p.name: _generated_at(p) for p in sorted(root.glob("*.md"))}
    assert after == before, "a degraded run restamped the dateline readers see"
    _record_identity("dateline", before, after)


def test_an_unnamed_exception_still_fails_loudly(stage):
    """The degradation path is for the TWO named failures. Anything else must keep
    exiting non-zero into run.sh's warn_and_page, or a real bug becomes a quiet freeze."""
    def boom(*a, **k):
        raise ValueError("a bug, not an outage")

    _induce(stage, boom)
    stage.use(DegradableClient(HUMANS))
    with pytest.raises(ValueError):
        run_cli(stage, "--dry-run")


def gharchive_ladder():
    from cerebro.gitintel.gharchive import TRANSPORT_LADDER_S
    return TRANSPORT_LADDER_S


def _generated_at(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("generated_at:"):
            return line.split(":", 1)[1].strip()
    return ""
