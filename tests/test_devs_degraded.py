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

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cerebro import config
from cerebro.__main__ import main
from cerebro.gitintel import devs_spike
from cerebro.gitintel import gharchive as _gharchive
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

    def __init__(self, logins, failing=()):
        self.logins = {x.lower(): x for x in logins}
        self.failing = {x.lower() for x in failing}
        self._calls = 0
        self._cache_hits = 0
        self._errors = 0

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
                          capsys=capsys, client=None, pages=[])

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


def _files(stage) -> set[str]:
    root = stage.vault / "_scratch" / "Devs" if stage.settings.dry_run \
        else stage.vault / "Devs"
    return {p.stem for p in root.glob("*.md")} if root.is_dir() else set()


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
