"""T12t — F066 the sanity gate. End-to-end with a fake ClickHouse transport."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from cerebro.gitintel import denylist, devs_spike
from cerebro.gitintel.devs_spike import DevRecord, sanity_check

FIXTURE = Path(__file__).parent / "fixtures" / "gharchive_cohort_90d.tsv"

VERDICTS_YAML = """
denied:
  - login: Dicklesworthstone
    verdict: automation
    shape: mass_self_repo
    evidence: "90d: 27764 pushes / 109 repos / 0 not-owned / 308.49 push per active day"
    reviewed_by: owner
    reviewed_on: 2026-08-26
cleared: []
"""


class FakeClient:
    """Resolves every owner to itself. No network."""

    def __init__(self, logins):
        self.logins = {x.lower(): x for x in logins}

    def get_user(self, login):
        real = self.logins.get((login or "").lower())
        if not real:
            return None
        return {"login": real, "type": "User", "name": real, "public_repos": 5}

    def request(self, path, params=None):
        return []


def _corpus(tmp_path, logins):
    d = tmp_path / "vault" / "Signals"
    d.mkdir(parents=True, exist_ok=True)
    for i, login in enumerate(logins):
        (d / f"n{i}.md").write_text(
            f"---\nurl: https://github.com/{login}/proj\n"
            f"captured: 2026-0{i % 9 + 1}-01T00:00:00+00:00\n---\nbody\n",
            encoding="utf-8")
    return tmp_path / "vault"


def _transport(body=None):
    text = body if body is not None else FIXTURE.read_text(encoding="utf-8")
    return lambda sql: text


def _verdicts(tmp_path, text=VERDICTS_YAML):
    p = tmp_path / "verdicts.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _run(tmp_path, logins, *, verdicts=None, limit=20, body=None, client=None):
    vault = _corpus(tmp_path, logins)
    return devs_spike.run(
        vault, tmp_path / "out", client=client or FakeClient(logins),
        verdicts_path=verdicts or _verdicts(tmp_path), limit=limit,
        log=lambda *a: None, transport=_transport(body))


HUMANS = ["simonw", "obra", "sindresorhus", "kentcdodds", "Rich-Harris", "paulmillr"]


# --- the happy path ----------------------------------------------------------

def test_end_to_end_produces_a_clean_ordered_top_list(tmp_path):
    result, top, records, paths = _run(tmp_path, HUMANS)
    assert result.ok, result.failures
    assert [r.login for r in top] == ["obra", "simonw", "Rich-Harris", "sindresorhus",
                                      "kentcdodds", "paulmillr"]
    days = [r.windows["90d"]["active_days"] for r in top]
    assert days == sorted(days, reverse=True)


def test_every_artifact_is_written(tmp_path):
    _, _, _, paths = _run(tmp_path, HUMANS)
    for key in ("top", "queue", "json"):
        assert paths[key].is_file() and paths[key].read_text(encoding="utf-8").strip()
    assert len(paths["sql"]) == 3
    for p in paths["sql"]:
        text = p.read_text(encoding="utf-8")
        assert "{" not in text, "a placeholder reached a file the validation step runs"


def test_the_top_artifact_carries_its_own_content_hash(tmp_path):
    _, _, _, paths = _run(tmp_path, HUMANS)
    body = paths["top"].read_text(encoding="utf-8")
    assert f"artifact-hash: {paths['hash']}" in body
    # the predicate and the eyeball must be provably about the SAME artifact
    import hashlib
    stem = body.split("\nartifact-hash:")[0]
    assert hashlib.sha256(stem.encode()).hexdigest()[:16] == paths["hash"]


def test_provenance_reaches_every_row(tmp_path):
    _, top, _, _ = _run(tmp_path, HUMANS)
    for r in top:
        assert r.provenance, f"{r.login} has no originating signal note"
        assert r.discovered_via == "vault"


# --- the predicate catches what it exists to catch ---------------------------

def _rec(login, state="clear"):
    return DevRecord(login=login, name=None, discovered_via="vault", provenance=["h"],
                     windows={}, pushes_per_week=[0] * 13,
                     automation={"state": state}, low_n=False, admitted=True,
                     reasons=[])


def test_predicate_catches_a_bot_login():
    r = sanity_check([_rec("renovate[bot]")], denylist.EMPTY)
    assert not r.ok and "renovate[bot]" in r.failures[0]


def test_predicate_catches_a_vendor_org():
    r = sanity_check([_rec("cloudflare")], denylist.EMPTY)
    assert not r.ok and "vendor org" in r.failures[0]


def test_predicate_catches_a_denied_login(tmp_path):
    v = denylist.load(_verdicts(tmp_path))
    r = sanity_check([_rec("Dicklesworthstone")], v)
    assert not r.ok and "denied verdict" in r.failures[0]


def test_predicate_catches_an_unresolved_flagged_account():
    r = sanity_check([_rec("someone", state="flagged")], denylist.EMPTY)
    assert not r.ok and "not clear" in r.failures[0]


def test_predicate_names_every_offender_not_just_the_first():
    r = sanity_check([_rec("a[bot]"), _rec("google"), _rec("c", "flagged")],
                     denylist.EMPTY)
    assert len(r.failures) == 3


def test_a_bot_shaped_login_without_the_bot_suffix_warns_and_never_fails():
    """The Court ruled name-pattern filtering provably insufficient, so this is a
    routing hint into the eyeball queue and nothing more. Failing on it would rebuild
    name filtering as an auto-exclude — the exact thing the ruling forbids — and would
    drop a human whose login happens to end in `-ci`."""
    r = sanity_check([_rec("renovate-bot"), _rec("deploy-ci")], denylist.EMPTY)
    assert r.ok is True and r.failures == []
    hits = [w for w in r.warnings if "ends in" in w]
    assert len(hits) == 2
    assert "renovate-bot" in hits[0] and "'-bot'" in hits[0]
    assert "deploy-ci" in hits[1] and "'-ci'" in hits[1]


def test_a_plain_human_login_raises_no_suffix_warning():
    r = sanity_check([_rec("simonw"), _rec("Rich-Harris"), _rec("t3dotgg")],
                     denylist.EMPTY)
    assert r.ok is True
    assert not [w for w in r.warnings if "ends in" in w]


def test_an_agent_recorded_clearing_is_named_in_the_warnings(tmp_path):
    """WHOSE EYE. Charter success criterion 4 is 'verified by eye'; an admission that
    rests on a verdict an AGENT recorded is not yet an admission the owner signed, and
    the run has to say so every time rather than at the launch probe."""
    from cerebro.gitintel.denylist import VerdictEntry, Verdicts
    agent = VerdictEntry(login="koala73", verdict="human", shape="fork_farm",
                         evidence="90d live: 960 pushes / 24 repos",
                         reviewed_by="e01-builder", reviewed_on="2026-08-26")
    owner = VerdictEntry(login="mvanhorn", verdict="human", shape="mass_self_repo",
                         evidence="90d live: 716 pushes / 204 repos",
                         reviewed_by="owner", reviewed_on="2026-08-26")
    v = Verdicts(cleared={"koala73": agent, "mvanhorn": owner})
    r = sanity_check([_rec("koala73"), _rec("mvanhorn"), _rec("simonw")], v)
    assert r.ok is True, "an agent-recorded verdict warns, it never blocks"
    hit = [w for w in r.warnings if "AGENT-recorded" in w]
    assert len(hit) == 1
    assert "koala73 (by e01-builder)" in hit[0]
    assert "mvanhorn" not in hit[0], "an owner-signed verdict is not outstanding"
    assert "simonw" not in hit[0], "an unflagged account needs no verdict at all"


def test_the_live_verdicts_file_is_honest_about_who_reviewed_what():
    """Not a mock. Every cleared entry that ships names its reviewer, and the split
    between owner-signed and agent-recorded is a fact of the file, not a claim."""
    from cerebro.gitintel import denylist as dl
    v = dl.load()
    assert v.cleared, "the cleared section is load-bearing and must not be empty"
    for entry in list(v.cleared.values()) + list(v.denied.values()):
        assert entry.reviewed_by.strip(), f"{entry.login}: no reviewer recorded"
    agent = [e.login for e in v.cleared.values() if not dl.is_owner_signed(e)]
    assert agent, ("if every clearing is owner-signed, delete the warning path rather "
                   "than letting it rot untested")


def test_zero_rows_is_a_failure_but_a_short_list_is_only_a_warning():
    assert sanity_check([], denylist.EMPTY).ok is False
    short = sanity_check([_rec("simonw")], denylist.EMPTY)
    assert short.ok is True and short.warnings


class BotResolvingClient(FakeClient):
    """Resolves one seed owner to a [bot] login and passes it through is_human.

    This is not hypothetical: F002's org -> top-committer fallback resolves an org repo
    to whoever pushes most, and the archive lane has repeatedly measured merge bots as
    the #1 pusher on PR-merge repos. The predicate must catch what the pre-filter let
    through, so here the pre-filter is deliberately bypassed."""

    def get_user(self, login):
        if (login or "").lower() == "simonw":
            return {"login": "merge-queue[bot]", "type": "User", "name": "bot",
                    "public_repos": 5}
        return super().get_user(login)


def test_a_planted_bot_reaching_the_top_list_fails_the_gate(tmp_path, monkeypatch):
    from cerebro.gitintel import owner_resolve
    monkeypatch.setattr(owner_resolve, "is_human", lambda u: bool(u))
    body = FIXTURE.read_text(encoding="utf-8").replace("simonw", "merge-queue[bot]")
    result, top, _, _ = _run(tmp_path, HUMANS, body=body,
                             client=BotResolvingClient(HUMANS))
    assert "merge-queue[bot]" in {r.login for r in top}   # the pre-filter did not stop it
    assert not result.ok                                  # the predicate did
    assert any("merge-queue[bot]" in f for f in result.failures)


def test_a_planted_denied_login_reaching_the_top_list_fails_the_gate(tmp_path):
    result, top, _, _ = _run(tmp_path, HUMANS + ["Dicklesworthstone"])
    # normally the automation floor withholds it; assert the predicate would also catch it
    r = sanity_check([_rec("Dicklesworthstone")],
                     denylist.load(_verdicts(tmp_path)))
    assert not r.ok


def test_a_flagged_account_is_withheld_from_the_top_list(tmp_path):
    """koala73 fires fork_farm with no verdict, so it never reaches the top list even
    though 81 active days would place it near the front."""
    result, top, records, _ = _run(tmp_path, HUMANS + ["koala73"])
    assert result.ok
    assert "koala73" not in {r.login for r in top}
    rec = next(r for r in records if r.login == "koala73")
    assert rec.automation["state"] == "flagged" and rec.admitted is False


def test_a_cleared_account_is_admitted_and_its_shapes_stay_visible(tmp_path):
    cleared = VERDICTS_YAML.replace("cleared: []", """cleared:
  - login: koala73
    verdict: human
    shape: fork_farm
    evidence: "90d: 960 pushes / 24 repos / all named worldmonitor, his own project"
    reviewed_by: owner
    reviewed_on: 2026-08-26
""")
    result, top, _, paths = _run(tmp_path, HUMANS + ["koala73"],
                                 verdicts=_verdicts(tmp_path, cleared))
    assert result.ok
    rec = next(r for r in top if r.login == "koala73")
    assert rec.automation["state"] == "clear"
    assert rec.automation["shapes"] == ["fork_farm"]      # transparent, not silent
    assert rec.automation["cleared_by"] == "owner"
    assert "cleared by owner" in paths["top"].read_text(encoding="utf-8")


def test_clearing_an_account_shrinks_the_queue_by_exactly_that_account(tmp_path):
    _, _, _, before = _run(tmp_path / "a", HUMANS + ["koala73", "can1357"])
    q1 = before["queue"].read_text(encoding="utf-8")
    assert "### koala73" in q1 and "### can1357" in q1

    cleared = VERDICTS_YAML.replace("cleared: []", """cleared:
  - login: koala73
    verdict: human
    shape: fork_farm
    evidence: "90d: 960 pushes / 24 repos, all one project"
    reviewed_by: owner
    reviewed_on: 2026-08-26
""")
    tmp2 = tmp_path / "b"
    tmp2.mkdir()
    _, _, _, after = _run(tmp2, HUMANS + ["koala73", "can1357"],
                          verdicts=_verdicts(tmp2, cleared))
    q2 = after["queue"].read_text(encoding="utf-8")
    assert "### koala73" not in q2          # left the queue
    assert "### can1357" in q2              # the rest is untouched
    assert "cleared by review — 1" in q2    # and appears as a standing decision


def test_the_queue_offers_both_blocks_and_writes_neither(tmp_path):
    """Auto-generating a verdict from a flag converts flag-for-review back into
    auto-exclude with extra steps. The human still has to paste one."""
    _, _, _, paths = _run(tmp_path, HUMANS + ["koala73"])
    q = paths["queue"].read_text(encoding="utf-8")
    assert "verdict: automation" in q and "verdict: human" in q
    assert denylist.load(_verdicts(tmp_path)).cleared == {}   # file untouched


# --- hard constraints: this epic writes nothing ------------------------------

SRC = Path("cerebro/gitintel/devs_spike.py").read_text(encoding="utf-8")


def test_the_spike_never_imports_signal():
    """crackscan.fetch() already leaks a crackscan/considered Signal per considered
    candidate. e01 is bound not to widen that, so this module cannot emit one."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "models" not in (node.module or "")
            assert all(a.name != "Signal" for a in node.names)
        if isinstance(node, ast.Import):
            assert all("models" not in a.name for a in node.names)


def _imported_modules():
    out = set()
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.ImportFrom):
            out.add((node.module or "").lstrip("."))
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_the_spike_never_imports_the_condemned_scorer():
    """The old scorer dies by not being called. Its WEIGHTS/threshold impossibility
    class must not reach the new path through an import."""
    assert not ({"crackscore", "metrics", "rank", "crackscan"} & _imported_modules())
    for banned in ("cheap_score", "deep_score", "WEIGHTS", "score_threshold"):
        assert banned not in SRC


def test_the_spike_never_writes_a_roster_or_the_cracked_devs_file():
    """Checked against the CODE with the module docstring stripped: the prose is allowed
    to say what the module refuses to write."""
    code = SRC.replace(ast.get_docstring(ast.parse(SRC)) or "", "")
    for banned in ("append_devs", "cracked_devs", "load_roster"):
        assert banned not in code
    assert "roster" not in _imported_modules()


def test_the_run_writes_nothing_outside_the_out_dir(tmp_path):
    vault = tmp_path / "vault"
    _corpus(tmp_path, HUMANS)
    before = sorted(p.name for p in (vault / "Signals").iterdir())
    _run(tmp_path, HUMANS)
    assert sorted(p.name for p in (vault / "Signals").iterdir()) == before
    assert not (vault / "Devs").exists()
    assert not (vault / "Entities").exists()


def test_the_run_returns_no_signal_objects(tmp_path):
    result, top, records, _ = _run(tmp_path, HUMANS)
    for r in records:
        assert isinstance(r, DevRecord)
        assert not hasattr(r, "source_tags")


# --- the record shape --------------------------------------------------------

def test_low_n_is_labelled_and_still_admitted(tmp_path):
    result, top, records, _ = _run(tmp_path, HUMANS + ["bcherny"])
    rec = next(r for r in records if r.login == "bcherny")
    assert rec.low_n is True and rec.admitted is True
    assert rec.login in {r.login for r in top}


def test_zero_activity_logins_are_labelled_never_dropped(tmp_path):
    result, top, records, _ = _run(tmp_path, HUMANS + ["never-pushed-at-all"])
    rec = next(r for r in records if r.login == "never-pushed-at-all")
    assert rec.windows["90d"]["active_days"] == 0
    assert rec.low_n is True and rec.admitted is True
    assert rec.pushes_per_week == [0] * 13


def test_the_run_json_is_deterministic_and_parses(tmp_path):
    _, _, _, paths = _run(tmp_path, HUMANS)
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert len(data) == len(HUMANS)
    assert all("automation" in d and "windows" in d for d in data)


def test_limit_caps_the_top_list(tmp_path):
    _, top, _, _ = _run(tmp_path, HUMANS, limit=3)
    assert len(top) == 3
