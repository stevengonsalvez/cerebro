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
DEVS = "python -m cerebro devs-refresh"
CONTRACT = "python -m cerebro devs-contract"
TOKEN = "python -m cerebro devs-token-check"
ADD = "add -- Daily Signals Weekly Devs"
COMMIT = "commit -S -m"
PUSH = " push"
CURL = "stub:curl:"

PYTHON_STUB = """#!/usr/bin/env bash
printf '%s\\n' "stub:python:$0 python $*" >> "$CALLLOG"
case "$*" in
  *push_failure*)               exit "${PUSH_FAILURE_RC:-0}" ;;
  *vault_path*)                 printf '%s\\n' "$FAKE_VAULT"; exit 0 ;;
  *VERCEL_DEPLOY_HOOK_URL*)     printf '%s\\n' "$FAKE_HOOK";  exit 0 ;;
  "-m cerebro roundup")         exit "${ROUNDUP_RC:-0}" ;;
  "-m cerebro devs-contract")   exit "${CONTRACT_RC:-0}" ;;
  "-m cerebro devs-token-check") exit "${TOKEN_RC:-0}" ;;
  "-m cerebro devs-refresh")    exit "${DEVS_RC:-0}" ;;
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
    (vault / "Devs").mkdir()

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
    assert sandbox.index(ROUNDUP) < sandbox.index(DEVS)
    assert sandbox.index(DEVS) < sandbox.index(ADD)
    assert sandbox.index(ADD) < sandbox.index(COMMIT)
    assert sandbox.index(PUSH) < sandbox.index(CURL)
    assert sandbox.count(CURL) == 1


def test_weekly_and_devs_are_staged_and_both_directories_exist(sandbox):
    sandbox.run()
    add = sandbox.calls[sandbox.index(ADD)]
    assert add.endswith("add -- Daily Signals Weekly Devs")
    assert (sandbox.vault / "Weekly").is_dir()
    assert (sandbox.vault / "Devs").is_dir()


def test_a_missing_weekly_directory_does_not_kill_the_push(sandbox):
    """Regression guard: `git add` exits 128 on a pathspec matching nothing, and under
    `set -e` that would abort the run before the daily briefing was ever pushed."""
    shutil.rmtree(sandbox.vault / "Weekly")
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert (sandbox.vault / "Weekly").is_dir()
    assert sandbox.count(PUSH) == 1


def test_a_failing_roundup_is_soft_but_still_pages(sandbox):
    """Soft, because the daily briefing must reach the vault regardless — but NOT
    silent: a roundup that stays broken stops weekly publication for good, and the only
    other trace is one line in an unrotated err.log nobody reads."""
    result = sandbox.run(ROUNDUP_RC=1)
    assert result.returncode == 0, result.stderr
    assert "weekly roundup failed" in result.stderr
    assert sandbox.count("push_failure") == 1
    for call in (ADD, COMMIT, PUSH):
        assert sandbox.count(call) == 1


def test_a_failing_deploy_hook_is_soft_but_still_pages(sandbox):
    result = sandbox.run(CURL_RC=1)
    assert result.returncode == 0, result.stderr
    assert sandbox.index(PUSH) < sandbox.index(CURL)
    assert "vercel deploy hook POST failed" in result.stderr
    assert sandbox.count("push_failure") == 1


def test_the_happy_path_pages_nobody(sandbox):
    """Negative control for the two cases above: paging must be failure-driven, not a
    thing that fires on every 07:00 run."""
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.count("push_failure") == 0


def test_alerting_can_never_turn_a_soft_failure_into_a_hard_one(sandbox):
    """If the pager itself is broken (no settings.yaml, no network, import error), the
    run must still exit 0 and still push the briefing."""
    result = sandbox.run(ROUNDUP_RC=1, PUSH_FAILURE_RC=1)
    assert result.returncode == 0, result.stderr
    assert sandbox.count("push_failure") == 1
    assert sandbox.count(PUSH) == 1


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


# --- F054/F055: the devs stage and the extended pathspec ----------------------
#
# WHY THE STAGE IS SOFT-FAIL AND WHY IT STILL PAGES. It is the same shape as the roundup
# line for the same reason: the daily briefing must reach the vault even when a later
# stage breaks. But it is NOT the same consequence when it stays broken — this is the
# stage that executes opt-out DELETIONS, so a permanently failing one leaves a removal
# request unhonoured. That is the one failure that must never be quiet, which is why the
# `|| warn_and_page` half is asserted as hard as the `||` half.

def test_the_devs_stage_runs_between_the_roundup_and_the_git_add(sandbox):
    """The slot is load-bearing in both directions: after the roundup so a broken devs
    stage cannot stop the weekly note, before `add` so what it writes is actually
    staged."""
    sandbox.run()
    assert sandbox.index(ROUNDUP) < sandbox.index(DEVS) < sandbox.index(ADD)


def test_a_failing_devs_stage_is_soft_but_still_pages(sandbox):
    result = sandbox.run(DEVS_RC=1)
    assert result.returncode == 0, result.stderr
    assert "devs refresh failed" in result.stderr
    assert sandbox.count("push_failure") == 1
    for call in (ADD, COMMIT, PUSH):
        assert sandbox.count(call) == 1


def test_a_failing_devs_stage_does_not_stop_the_roundup_from_having_run(sandbox):
    sandbox.run(DEVS_RC=1)
    assert sandbox.count(ROUNDUP) == 1


def test_both_soft_stages_failing_still_commits_and_pushes_and_pages_twice(sandbox):
    result = sandbox.run(ROUNDUP_RC=1, DEVS_RC=1)
    assert result.returncode == 0, result.stderr
    assert sandbox.count("push_failure") == 2
    assert sandbox.count(PUSH) == 1


def test_the_happy_path_still_pages_nobody_with_the_stage_added(sandbox):
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.count("push_failure") == 0


def test_the_devs_refresh_call_carries_no_write_flag(sandbox):
    """Config-driven, exactly like the roundup. A hardcoded --write here would make a dev
    checkout write real Devs/ notes into whatever vault it is pointed at."""
    sandbox.run()
    calls = [c for c in sandbox.calls if "-m cerebro devs-refresh" in c]
    assert calls == ["stub:python:.venv/bin/python python -m cerebro devs-refresh"]


def test_a_missing_devs_directory_does_not_kill_the_push(sandbox):
    """`git add` exits 128 on a pathspec matching nothing. Devs/ legitimately may not
    exist: the writer never creates an empty one, so a run that published nobody leaves
    no directory at all."""
    shutil.rmtree(sandbox.vault / "Devs")
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert (sandbox.vault / "Devs").is_dir()
    assert sandbox.count(PUSH) == 1


def test_the_git_stub_reproduces_the_exit_128_landmine_for_devs_too(sandbox):
    """Negative control: without run.sh's `mkdir -p`, staging a non-existent `Devs`
    really does fail the way real git fails."""
    shutil.rmtree(sandbox.vault / "Devs")
    out = subprocess.run(
        ["git", "-C", str(sandbox.vault), "add", "--",
         "Daily", "Signals", "Weekly", "Devs"],
        env=sandbox.env(), capture_output=True, text=True,
    )
    assert out.returncode == 128
    assert "did not match any files" in out.stderr


def test_the_run_sh_diff_against_devs_writer_is_exactly_two_added_commands():
    """THE TRIPWIRE, RE-BASED ON `f/devs-writer` AND RIDING THE LINE IT GUARDS.

    e06 adds two commands to the launchd entrypoint — the F069 contract preflight and
    the F059 token check — in two different commits six tasks apart. The count is a
    statement about the tree AS IT STANDS, so it was bumped by the commit that added each
    line: 1 at the contract check, 2 here. Jumping it ahead of its subject would have
    redded the suite for every commit in between; softening it to a range would retire
    the tripwire entirely.

    COMMENT LINES ARE COUNTED SEPARATELY, not ignored. This file's house style is dense
    rationale beside every soft-fail, and a comment cannot change what the script does;
    what must stay reviewable is the number of COMMANDS. Both numbers are asserted.
    """
    base = subprocess.run(
        ["git", "diff", "--unified=0", "f/devs-writer", "--", "scripts/run.sh"],
        cwd=REPO, capture_output=True, text=True)
    if base.returncode != 0:
        pytest.skip("f/devs-writer is not present in this checkout")
    added = [ln[1:] for ln in base.stdout.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in base.stdout.splitlines()
               if ln.startswith("-") and not ln.startswith("---")]
    commands = [ln for ln in added if ln.strip() and not ln.lstrip().startswith("#")]
    comments = [ln for ln in added if ln.lstrip().startswith("#")]
    assert commands == [
        '.venv/bin/python -m cerebro devs-contract || warn_and_page '
        '"gh archive contract check failed"',
        '.venv/bin/python -m cerebro devs-token-check || warn_and_page '
        '"gh token check failed"'], commands
    assert len(comments) == 8, comments
    assert removed == [], removed


# --- F069: the preflight is advisory, never a gate ----------------------------

def test_the_contract_check_runs_before_the_devs_refresh(sandbox):
    """A preflight that ran after the stage it is meant to precede would report on a
    contract the run had already used."""
    sandbox.run()
    assert sandbox.index(ROUNDUP) < sandbox.index(CONTRACT)
    assert sandbox.index(CONTRACT) < sandbox.index(DEVS)


@pytest.mark.parametrize("rc", [3, 4])
def test_a_failing_contract_check_still_lets_the_refresh_run(sandbox, rc):
    """THE WHOLE REASON IT IS NOT A GATE. Exit 3 is drift and exit 4 is an unreachable
    endpoint; on either morning the refresh must still run, because it has its own
    degradation path and blocking it would turn a hiccup into a self-inflicted outage."""
    result = sandbox.run(CONTRACT_RC=rc)
    assert result.returncode == 0, result.stderr
    assert sandbox.count(DEVS) == 1
    assert sandbox.count(PUSH) == 1


def test_a_failing_contract_check_pages_exactly_once(sandbox):
    result = sandbox.run(CONTRACT_RC=3)
    assert "gh archive contract check failed" in result.stderr
    assert sandbox.count("push_failure") == 1


def test_a_failing_contract_check_does_not_page_for_the_refresh_as_well(sandbox):
    """Two soft-failing neighbours, two independent pages: a contract failure must not
    be reported as a refresh failure, which is the misdiagnosis F069 exists to end."""
    result = sandbox.run(CONTRACT_RC=3, DEVS_RC=1)
    assert result.returncode == 0
    assert sandbox.count("push_failure") == 2
    assert "gh archive contract check failed" in result.stderr
    assert "devs refresh failed" in result.stderr


def test_the_contract_check_carries_no_flags(sandbox):
    """No --offline in production: the preflight checks the real endpoint or it checks
    nothing."""
    sandbox.run()
    calls = [c for c in sandbox.calls if "-m cerebro devs-contract" in c]
    assert calls == ["stub:python:.venv/bin/python python -m cerebro devs-contract"]


# --- the F052 takedown path rides this exact pathspec -------------------------

def test_the_extended_pathspec_stages_a_devs_deletion_as_a_real_git_delete(tmp_path):
    """REAL GIT, NOT THE STUB. F052's promise is "removed within one deploy cycle", and
    the mechanism is that `git add -- ... Devs` stages a DELETION, not only an addition.
    If it did not, an opt-out would remove the note from this Mac and leave the page live
    on the public site for ever."""
    repo = tmp_path / "vault"
    # Every directory run.sh's `mkdir -p` guarantees, so the pathspec under test is the
    # WHOLE one the script actually runs rather than a convenient subset.
    for sub in ("Daily", "Signals", "Weekly", "Devs"):
        (repo / sub).mkdir(parents=True)
    (repo / "Devs" / "gone.md").write_text("a note\n", encoding="utf-8")
    (repo / "Daily" / "d.md").write_text("daily\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def git(*argv):
        return subprocess.run(["git", "-C", str(repo), *argv], env=env,
                              capture_output=True, text=True)

    assert git("init", "-q").returncode == 0
    git("add", "-A")
    assert git("commit", "-q", "-m", "seed", "--no-gpg-sign").returncode == 0

    (repo / "Devs" / "gone.md").unlink()
    assert git("add", "--", "Daily", "Signals", "Weekly", "Devs").returncode == 0
    staged = git("diff", "--cached", "--name-status").stdout
    assert "D\tDevs/gone.md" in staged, staged


# --- F059: the token check is the second advisory preflight -------------------

def test_the_token_check_runs_between_the_contract_check_and_the_refresh(sandbox):
    sandbox.run()
    assert sandbox.index(CONTRACT) < sandbox.index(TOKEN)
    assert sandbox.index(TOKEN) < sandbox.index(DEVS)


@pytest.mark.parametrize("rc", [5, 6])
def test_a_failing_token_check_still_lets_the_refresh_run(sandbox, rc):
    """5 is over-scoped or refused, 6 is "no token reached the process". Either is a
    credential problem, and neither is a reason to stop publishing what the lane can
    still read — the pool query needs no token at all."""
    result = sandbox.run(TOKEN_RC=rc)
    assert result.returncode == 0, result.stderr
    assert sandbox.count(DEVS) == 1
    assert sandbox.count(PUSH) == 1


def test_a_failing_token_check_pages_once_with_its_own_message(sandbox):
    result = sandbox.run(TOKEN_RC=5)
    assert "gh token check failed" in result.stderr
    assert "contract" not in result.stderr
    assert sandbox.count("push_failure") == 1


def test_all_three_preflights_can_fail_independently(sandbox):
    result = sandbox.run(CONTRACT_RC=3, TOKEN_RC=5, DEVS_RC=1)
    assert result.returncode == 0
    assert sandbox.count("push_failure") == 3
    assert sandbox.count(PUSH) == 1


def test_the_token_check_carries_no_flags(sandbox):
    sandbox.run()
    calls = [c for c in sandbox.calls if "-m cerebro devs-token-check" in c]
    assert calls == ["stub:python:.venv/bin/python python -m cerebro devs-token-check"]
