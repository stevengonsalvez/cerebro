"""`cerebro devs-refresh` — the stage `run.sh` calls.

THE TWO PROPERTIES THAT MATTER ARE BOTH ABOUT NOT WRITING. A failing sanity gate writes
ZERO notes and exits non-zero; an unreadable consent file exits non-zero before a single
query is rendered. Everything else is plumbing.
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

FIXTURE = Path(__file__).parent / "fixtures" / "gharchive_cohort_90d.tsv"
HUMANS = ["simonw", "obra", "sindresorhus", "kentcdodds", "Rich-Harris", "paulmillr"]


class FakeClient:
    def __init__(self, logins):
        self.logins = {x.lower(): x for x in logins}
        self.paths: list[str] = []
        self._calls = 0
        self._cache_hits = 0

    def get_user(self, login):
        real = self.logins.get((login or "").lower())
        return None if not real else {"login": real, "type": "User", "name": real}

    def request(self, path, params=None):
        self.paths.append(path)
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


def optout_file(tmp_path, *logins) -> Path:
    body = "logins: []\n" if not logins else "logins:\n" + "".join(
        f'  - login: "{x}"\n' for x in logins)
    p = tmp_path / "devs_optout.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def verdicts_file(tmp_path, body="denied: []\ncleared: []\n") -> Path:
    p = tmp_path / "verdicts.yaml"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def harness(tmp_path, monkeypatch, capsys):
    """Drives the REAL `main()` with a fake ClickHouse transport and a fake client."""
    vault = corpus(tmp_path, HUMANS)
    # A DECOY, deliberately different from the `--vault` the CLI is given. If `--vault`
    # moved only where the run READS, the corpus would land here and every "the corpus is
    # under the vault we asked for" assertion below would be checking the wrong disk.
    decoy = tmp_path / "configured-vault"
    decoy.mkdir()
    settings = SimpleNamespace(vault_path=decoy, dry_run=True, sources={},
                               github={"cache_path": ":memory:"})
    monkeypatch.setattr(config, "load", lambda **kw: settings)
    import cerebro.__main__ as main_mod
    monkeypatch.setattr(main_mod, "load", lambda **kw: settings, raising=False)
    monkeypatch.setattr("cerebro.gitintel.github_client.GitHubClient",
                        lambda settings=None, token=None, cache=None:
                        FakeClient(HUMANS))
    monkeypatch.setattr("cerebro.gitintel.gharchive.pool_metrics",
                        _fake_pool_metrics)
    monkeypatch.setattr(devs_spike.gharchive, "pool_metrics", _fake_pool_metrics)
    return SimpleNamespace(tmp_path=tmp_path, vault=vault, settings=settings,
                           decoy=decoy, capsys=capsys)


#: Bound BEFORE any monkeypatch so the fake cannot call itself. A `from ... import` inside
#: the fake resolves the PATCHED attribute and recurses until the stack ends.
_REAL_POOL_METRICS = _gharchive.pool_metrics


def _fake_pool_metrics(logins, windows=(7, 30, 90), transport=None, **kw):
    text = FIXTURE.read_text(encoding="utf-8")
    return _REAL_POOL_METRICS(logins, windows=windows, transport=lambda sql: text)


def run_cli(harness, *argv) -> int:
    args = ["cerebro", "devs-refresh", "--vault", str(harness.vault),
            "--out", str(harness.tmp_path / "out"), *argv]
    old = sys.argv
    sys.argv = args
    try:
        main()
        return 0
    except SystemExit as exc:
        code = exc.code
        # argparse and the lane guard both exit with a STRING; `int(...)` on one is a
        # ValueError that hides the real assertion.
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    finally:
        sys.argv = old


def summary(harness) -> dict:
    text = harness.capsys.readouterr().out
    start = text.index("{")
    return json.loads(text[start:])


# --- the happy path ------------------------------------------------------------

def test_a_dry_run_writes_the_corpus_under_scratch_and_nothing_else(harness):
    code = run_cli(harness, "--dry-run",
                   "--optout", str(optout_file(harness.tmp_path)),
                   "--verdicts", str(verdicts_file(harness.tmp_path)))
    assert code == 0
    out = summary(harness)
    assert out["dry_run"] is True and out["stage"] == "devs-refresh"
    scratch = harness.vault / "_scratch" / "Devs"
    assert scratch.is_dir() and list(scratch.glob("*.md"))
    assert out["written"] == len(list(scratch.glob("*.md")))
    assert not (harness.vault / "Devs").exists(), \
        "a dry run must never touch the real corpus directory"
    # The corpus lands under the --vault root, not under settings.vault_path.
    assert Path(out["corpus_dir"]) == scratch
    assert list(harness.decoy.rglob("*")) == []


def test_the_withheld_report_and_the_budget_land_in_the_out_dir_not_the_vault(harness):
    run_cli(harness, "--dry-run", "--optout", str(optout_file(harness.tmp_path)),
            "--verdicts", str(verdicts_file(harness.tmp_path)))
    out = summary(harness)
    report = Path(out["withheld_report"])
    assert report.is_file() and report.parent == harness.tmp_path / "out"
    assert "THE WRITE GATE IS THE PUBLISH GATE" in report.read_text(encoding="utf-8")
    assert Path(out["artifacts"]["budget"]).is_file()
    # Nothing the run wrote lives anywhere under the vault except _scratch/.
    stray = [p for p in harness.vault.rglob("*")
             if p.is_file() and "_scratch" not in p.parts and "Signals" not in p.parts]
    assert stray == []


def test_the_corpus_is_reconciled_rather_than_appended(harness):
    scratch = harness.vault / "_scratch" / "Devs"
    scratch.mkdir(parents=True)
    (scratch / "someonewhoisgone.md").write_text("stale\n", encoding="utf-8")
    run_cli(harness, "--dry-run", "--optout", str(optout_file(harness.tmp_path)),
            "--verdicts", str(verdicts_file(harness.tmp_path)))
    out = summary(harness)
    assert out["deleted_churn"] == 1
    assert not (scratch / "someonewhoisgone.md").exists()


def test_an_opted_out_login_gets_no_note_and_loses_the_one_it_had(harness):
    scratch = harness.vault / "_scratch" / "Devs"
    scratch.mkdir(parents=True)
    (scratch / "simonw.md").write_text("yesterday's note\n", encoding="utf-8")
    run_cli(harness, "--dry-run",
            "--optout", str(optout_file(harness.tmp_path, "simonw")),
            "--verdicts", str(verdicts_file(harness.tmp_path)))
    out = summary(harness)
    assert out["deleted_consent"] == 1
    assert not (scratch / "simonw.md").exists()


# --- the two ways it must write nothing ------------------------------------------

def test_a_malformed_consent_file_exits_non_zero_with_nothing_written(harness):
    bad = harness.tmp_path / "bad.yaml"
    bad.write_text("logins: not-a-list\n", encoding="utf-8")
    code = run_cli(harness, "--dry-run", "--optout", str(bad))
    assert code == 2
    assert "NOTHING WAS WRITTEN" in harness.capsys.readouterr().out
    assert not (harness.vault / "_scratch").exists()


def test_a_failing_sanity_gate_writes_zero_notes_and_exits_one(harness, monkeypatch):
    from cerebro.gitintel.devs_spike import SanityResult
    monkeypatch.setattr(devs_spike, "sanity_check",
                        lambda top, verdicts: SanityResult(
                            ok=False, failures=["a planted bot reached the top list"],
                            warnings=[]))
    code = run_cli(harness, "--dry-run",
                   "--optout", str(optout_file(harness.tmp_path)),
                   "--verdicts", str(verdicts_file(harness.tmp_path)))
    assert code == 1
    assert "NOTHING WAS WRITTEN" in harness.capsys.readouterr().out
    assert not (harness.vault / "_scratch" / "Devs").exists()


def test_a_failing_sanity_gate_does_not_delete_the_previous_corpus(harness, monkeypatch):
    """SHIP NOTHING means exactly that: not a partial corpus, and not an empty one."""
    from cerebro.gitintel.devs_spike import SanityResult
    scratch = harness.vault / "_scratch" / "Devs"
    scratch.mkdir(parents=True)
    (scratch / "yesterday.md").write_text("still here\n", encoding="utf-8")
    monkeypatch.setattr(devs_spike, "sanity_check",
                        lambda top, verdicts: SanityResult(
                            ok=False, failures=["gate red"], warnings=[]))
    run_cli(harness, "--dry-run", "--optout", str(optout_file(harness.tmp_path)),
            "--verdicts", str(verdicts_file(harness.tmp_path)))
    assert (scratch / "yesterday.md").is_file()


# --- the tri-state, which is what run.sh depends on --------------------------------

def test_the_no_flag_form_defers_to_settings_and_does_not_force_a_write(harness):
    """run.sh calls this with NO flag. Coercing the no-flag form to a write would make a
    dev checkout write real notes into whatever vault it is pointed at."""
    code = run_cli(harness, "--optout", str(optout_file(harness.tmp_path)),
                   "--verdicts", str(verdicts_file(harness.tmp_path)))
    assert code == 0
    assert summary(harness)["dry_run"] is True
    assert (harness.vault / "_scratch" / "Devs").is_dir()
    assert not (harness.vault / "Devs").exists()


def test_write_is_available_but_never_implicit(harness):
    harness.settings.dry_run = False
    code = run_cli(harness, "--write", "--optout", str(optout_file(harness.tmp_path)),
                   "--verdicts", str(verdicts_file(harness.tmp_path)))
    assert code == 0
    assert summary(harness)["dry_run"] is False
    assert (harness.vault / "Devs").is_dir()


def test_dry_run_and_write_are_mutually_exclusive(harness):
    assert run_cli(harness, "--dry-run", "--write") != 0


def test_an_unknown_lane_is_rejected(harness):
    assert run_cli(harness, "--dry-run", "--lanes", "nonsense") != 0


# --- the copy the stage emits ------------------------------------------------------

def test_no_output_implies_a_human_picked_anybody(harness):
    run_cli(harness, "--dry-run", "--optout", str(optout_file(harness.tmp_path)),
            "--verdicts", str(verdicts_file(harness.tmp_path)))
    text = harness.capsys.readouterr().out.lower()
    for banned in ("hand-picked", "handpicked", "human-reviewed", "cracked", "elite"):
        assert banned not in text


def test_the_module_entrypoint_can_actually_run_the_stage(tmp_path):
    """REGRESSION GUARD, AND IT COST A REAL RUN TO FIND. Every other test in this file
    imports `main` from a fully-loaded module, so a helper defined BELOW the
    `if __name__ == "__main__"` guard resolves fine here and raises `NameError` the
    moment `python -m cerebro` executes the module top to bottom. Asserted structurally:
    nothing may be defined after the guard."""
    import ast
    src = Path("cerebro/__main__.py").read_text(encoding="utf-8")
    body = ast.parse(src).body
    guard_at = next(
        i for i, node in enumerate(body)
        if isinstance(node, ast.If) and ast.unparse(node.test).startswith("__name__"))
    after = [type(n).__name__ for n in body[guard_at + 1:]]
    assert after == [], (
        f"{after} are defined after the __main__ guard and are therefore undefined "
        f"while main() runs under `python -m cerebro`")
