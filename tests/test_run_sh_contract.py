"""`scripts/run.sh` behavioural contract.

run.sh is the launchd entrypoint: if it breaks, the daily briefing silently stops
reaching the vault. These tests drive the REAL script inside a hermetic sandbox whose
`git`, `curl` and `.venv/bin/python` are logging stubs, so ordering, soft-fail and
alerting are asserted as behaviour rather than read off the source.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUN_SH = REPO / "scripts" / "run.sh"

# Needles into the call log. git is always invoked as `git -C <vault> <subcommand>`,
# so the subcommand tail is what identifies a call, not the word "git".
DAILY = "python -m cerebro"
ROUNDUP = "python -m cerebro roundup"
ADD = "add -- Daily Signals Weekly"
COMMIT = "commit -S -m"
PUSH = " push"
CURL = "stub:curl:"

PYTHON_STUB = """#!/usr/bin/env bash
printf '%s\\n' "stub:python:$0 python $*" >> "$CALLLOG"
case "$*" in
  *push_failure*)               exit 0 ;;
  *vault_path*)                 printf '%s\\n' "$FAKE_VAULT"; exit 0 ;;
  *VERCEL_DEPLOY_HOOK_URL*)     printf '%s\\n' "$FAKE_HOOK";  exit 0 ;;
  "-m cerebro roundup")         exit "${ROUNDUP_RC:-0}" ;;
  "-m cerebro")                 exit "${CEREBRO_RC:-0}" ;;
esac
exit 0
"""

# Faithful stand-in for the two git behaviours run.sh depends on: `add` exits 128 on a
# pathspec that matches nothing (the landmine `mkdir -p` defuses), and
# `diff --cached --quiet` exits 1 when something IS staged.
GIT_STUB = """#!/usr/bin/env bash
printf '%s\\n' "stub:git:$0 git $*" >> "$CALLLOG"
if [ "${3:-}" = "add" ]; then
  vault="$2"; shift 4
  for spec in "$@"; do
    if [ ! -e "$vault/$spec" ]; then
      echo "fatal: pathspec '$spec' did not match any files" >&2
      exit 128
    fi
  done
  exit 0
fi
case "$*" in
  *"diff --cached --quiet"*) exit "${GIT_DIFF_RC:-1}" ;;
  *" push"*)                 exit "${GIT_PUSH_RC:-0}" ;;
esac
exit 0
"""

CURL_STUB = """#!/usr/bin/env bash
printf '%s\\n' "stub:curl:$0 curl $*" >> "$CALLLOG"
exit "${CURL_RC:-0}"
"""


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path: Path):
    repo = tmp_path / "fakerepo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(RUN_SH, repo / "scripts" / "run.sh")
    (repo / "scripts" / "run.sh").chmod(0o755)

    (repo / ".venv" / "bin").mkdir(parents=True)
    _exe(repo / ".venv" / "bin" / "python", PYTHON_STUB)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    _exe(bindir / "git", GIT_STUB)
    _exe(bindir / "curl", CURL_STUB)

    vault = tmp_path / "vault"
    for sub in ("Daily", "Signals"):
        (vault / sub).mkdir(parents=True)
    (vault / "Weekly").mkdir()

    calllog = tmp_path / "calls.log"
    calllog.write_text("")
    return SimpleSandbox(tmp_path, repo, bindir, vault, calllog)


class SimpleSandbox:
    def __init__(self, root, repo, bindir, vault, calllog):
        self.root, self.repo, self.bindir = root, repo, bindir
        self.vault, self.calllog = vault, calllog

    def env(self, **extra) -> dict:
        # HOME inside tmp_path is what makes the sandbox hermetic: run.sh re-prepends
        # "$HOME/.local/bin" and an nvm glob to PATH, so without this the real git/curl
        # could shadow the stubs and every assertion below would be vacuous.
        env = {
            **os.environ,
            "HOME": str(self.root),
            "PATH": f"{self.bindir}:{os.environ['PATH']}",
            "CALLLOG": str(self.calllog),
            "FAKE_VAULT": str(self.vault),
            "FAKE_HOOK": "https://hook.invalid/deploy/token",
        }
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def run(self, **extra) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.repo / "scripts" / "run.sh")],
            env=self.env(**extra), capture_output=True, text=True,
        )

    @property
    def calls(self) -> list[str]:
        return [ln for ln in self.calllog.read_text().splitlines() if ln]

    def index(self, needle: str) -> int:
        for i, line in enumerate(self.calls):
            if needle in line:
                return i
        raise AssertionError(f"{needle!r} not in call log:\n" + "\n".join(self.calls))

    def count(self, needle: str) -> int:
        return sum(1 for line in self.calls if needle in line)


def test_run_sh_is_syntactically_valid():
    assert subprocess.run(["bash", "-n", str(RUN_SH)]).returncode == 0


def test_the_sandbox_actually_shadows_the_real_git_and_curl(sandbox):
    """If this fails the harness is exercising the real binaries and every other
    case in this file proves nothing."""
    header = "\n".join(RUN_SH.read_text().splitlines()[:8])
    probe = sandbox.repo / "probe.sh"
    probe.write_text(f"{header}\ncommand -v git\ncommand -v curl\n")
    out = subprocess.run(["bash", str(probe)], env=sandbox.env(),
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == [str(sandbox.bindir / "git"), str(sandbox.bindir / "curl")]


def test_happy_path_orders_pipeline_roundup_stage_push_hook(sandbox):
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.index(DAILY) < sandbox.index(ROUNDUP)
    assert sandbox.index(ROUNDUP) < sandbox.index(ADD)
    assert sandbox.index(ADD) < sandbox.index(COMMIT)
    assert sandbox.index(PUSH) < sandbox.index(CURL)
    assert sandbox.count(CURL) == 1


def test_weekly_is_staged_and_the_directory_exists_when_it_is(sandbox):
    sandbox.run()
    add = sandbox.calls[sandbox.index(ADD)]
    assert add.endswith("add -- Daily Signals Weekly")
    assert (sandbox.vault / "Weekly").is_dir()


def test_a_missing_weekly_directory_does_not_kill_the_push(sandbox):
    """Regression guard: `git add` exits 128 on a pathspec matching nothing, and under
    `set -e` that would abort the run before the daily briefing was ever pushed."""
    shutil.rmtree(sandbox.vault / "Weekly")
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert (sandbox.vault / "Weekly").is_dir()
    assert sandbox.count(PUSH) == 1


def test_a_failing_roundup_is_soft_and_the_briefing_still_ships(sandbox):
    result = sandbox.run(ROUNDUP_RC=1)
    assert result.returncode == 0, result.stderr
    assert "weekly roundup failed" in result.stderr
    for call in (ADD, COMMIT, PUSH):
        assert sandbox.count(call) == 1


def test_a_failing_deploy_hook_is_soft(sandbox):
    result = sandbox.run(CURL_RC=1)
    assert result.returncode == 0, result.stderr
    assert sandbox.index(PUSH) < sandbox.index(CURL)
    assert "vercel deploy hook POST failed" in result.stderr


def test_a_failing_vault_push_is_loud_and_pages_the_phone(sandbox):
    result = sandbox.run(GIT_PUSH_RC=1)
    assert result.returncode != 0
    assert sandbox.count("push_failure") == 1


def test_no_staged_changes_means_no_commit_no_push_no_hook(sandbox):
    result = sandbox.run(GIT_DIFF_RC=0)
    assert result.returncode == 0, result.stderr
    assert sandbox.count(COMMIT) == 0
    assert sandbox.count(PUSH) == 0
    assert sandbox.count(CURL) == 0


def test_an_unset_hook_url_skips_the_curl_entirely(sandbox):
    result = sandbox.run(FAKE_HOOK="")
    assert result.returncode == 0, result.stderr
    assert sandbox.count(PUSH) == 1
    assert sandbox.count(CURL) == 0


def test_the_roundup_call_carries_no_write_flag(sandbox):
    """run.sh must stay config-driven. A hardcoded --write here would make a dev
    checkout write real Weekly/ notes into whatever vault it is pointed at."""
    sandbox.run()
    roundup_calls = [c for c in sandbox.calls if "-m cerebro roundup" in c]
    assert roundup_calls == ["stub:python:.venv/bin/python python -m cerebro roundup"]


def test_the_git_stub_reproduces_the_exit_128_landmine(sandbox):
    """Negative control for the test above: without run.sh's `mkdir -p`, staging a
    non-existent `Weekly` really does fail the way real git fails. Without this the
    missing-directory guard would pass vacuously."""
    shutil.rmtree(sandbox.vault / "Weekly")
    out = subprocess.run(
        ["git", "-C", str(sandbox.vault), "add", "--", "Daily", "Signals", "Weekly"],
        env=sandbox.env(), capture_output=True, text=True,
    )
    assert out.returncode == 128
    assert "did not match any files" in out.stderr
