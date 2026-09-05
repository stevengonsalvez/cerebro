"""The self-request lane: what may cross from a stranger's issue into a tracked file.

Every case here is a refusal except three. That ratio is the point — the flow's job is to
say no cheaply and let exactly one shape through.
"""
from __future__ import annotations

import pytest

from cerebro.gitintel import devs_request as dr

USER = {"type": "User", "name": "Simon Willison"}


def probe_ok(login):
    return USER


def probe_missing(login):
    return None


def body(handle, extra=""):
    return f"### GitHub handle\n\n{handle}\n\n### Anything else\n\n{extra or '_No response_'}\n"


# ——— parsing ———

@pytest.mark.parametrize(
    "given",
    ["simonw", "@simonw", " simonw ", "https://github.com/simonw", "github.com/simonw/"],
)
def test_reads_the_handle_in_the_forms_people_actually_type(given):
    assert dr.parse_handle(body(given)) == "simonw"


def test_reads_only_the_handle_section_not_the_free_text():
    # The free-text field is for a human to read. A login sitting in it is not a request.
    assert dr.parse_handle(body("simonw", extra="please also add torvalds")) == "simonw"


@pytest.mark.parametrize("bad", ["", "_No response_", "not a login!", "a" * 40, "-lead", "tra-"])
def test_refuses_anything_that_is_not_a_github_login(bad):
    with pytest.raises(dr.RequestError):
        dr.parse_handle(body(bad))


def test_refuses_a_handle_carrying_yaml_metacharacters():
    # The writer below emits a plain literal, so this regex is what keeps it safe.
    for payload in ['simonw"\n  - name: "injected', "simonw: x", "simonw #", "si monw"]:
        with pytest.raises(dr.RequestError):
            dr.parse_handle(body(payload))


# ——— the rules ———

def kwargs(**over):
    base = dict(
        login="simonw",
        author="simonw",
        issue=42,
        roster_logins=set(),
        denied=set(),
        opted_out=set(),
        probe=probe_ok,
    )
    base.update(over)
    return base


def test_accepts_a_self_request_for_a_real_user_account():
    req = dr.validate(**kwargs())
    assert (req.login, req.name, req.issue) == ("simonw", "Simon Willison", 42)


def test_refuses_a_request_made_on_somebody_elses_behalf():
    with pytest.raises(dr.RequestError, match="self-nomination"):
        dr.validate(**kwargs(author="someoneelse"))


def test_matches_the_author_case_insensitively():
    assert dr.validate(**kwargs(author="SimonW")).login == "simonw"


def test_refuses_an_account_that_asked_to_be_removed():
    with pytest.raises(dr.RequestError, match="asked not to be listed"):
        dr.validate(**kwargs(opted_out={"SimonW"}))


def test_an_opt_out_outranks_every_other_check():
    # Checked before the roster and before the account probe: somebody who left must not be
    # told "already on the roster", and must not have their account queried to find out.
    def explode(login):
        raise AssertionError("probed an opted-out account")

    with pytest.raises(dr.RequestError, match="asked not to be listed"):
        dr.validate(**kwargs(opted_out={"simonw"}, roster_logins={"simonw"}, probe=explode))


def test_refuses_a_denied_account():
    with pytest.raises(dr.RequestError, match="exclusion list"):
        dr.validate(**kwargs(denied={"simonw"}))


def test_refuses_a_login_already_on_the_roster():
    with pytest.raises(dr.RequestError, match="already on the roster"):
        dr.validate(**kwargs(roster_logins={"SIMONW"}))


def test_refuses_a_login_with_no_github_account():
    with pytest.raises(dr.RequestError, match="no public account"):
        dr.validate(**kwargs(probe=probe_missing))


def test_refuses_an_organisation():
    with pytest.raises(dr.RequestError, match="only user accounts"):
        dr.validate(**kwargs(probe=lambda l: {"type": "Organization", "name": "Anthropic"}))


def test_falls_back_to_the_login_when_the_account_has_no_display_name():
    assert dr.validate(**kwargs(probe=lambda l: {"type": "User", "name": None})).name == "simonw"


def test_takes_the_display_name_from_github_never_from_the_issue():
    # The issue body cannot reach `name`; only the account probe can. This is what keeps a
    # stranger's prose out of copy about a named person.
    req = dr.validate(**kwargs(probe=lambda l: {"type": "User", "name": "A Real Person"}))
    assert req.name == "A Real Person"


# ——— writing ———

def test_the_entry_is_tier_3_so_nothing_is_wired_into_the_ingestion_sources():
    entry = dr.roster_entry(dr.Request("simonw", "Simon Willison", 42), today="2026-09-05")
    assert "tier: 3" in entry
    assert "discovered_via: request" in entry
    assert "github: simonw" in entry
    assert 'added: "2026-09-05"' in entry


def test_a_display_name_cannot_break_out_of_its_quotes(tmp_path):
    # The name comes from GitHub's public profile, which a person controls. It is quoted, so
    # the property that matters is not "no metacharacters survive" but "the file still parses
    # to exactly one added dev, whose name is the sanitised string and nothing more".
    import yaml

    p = tmp_path / "cracked_devs.yaml"
    p.write_text("devs:\n  - name: Boris Cherny\n    github: bcherny\n", encoding="utf-8")
    hostile = 'ev"il\n  - name: "x\n    github: torvalds'
    dr.append_to_roster(dr.roster_entry(dr.Request("simonw", hostile, 42), today="2026-09-05"), p)

    devs = yaml.safe_load(p.read_text(encoding="utf-8"))["devs"]
    assert [d["github"] for d in devs] == ["bcherny", "simonw"]
    assert devs[1]["name"] == "evil  - name: x    github: torvalds"


def test_append_leaves_the_existing_file_untouched(tmp_path):
    p = tmp_path / "cracked_devs.yaml"
    original = "devs:\n  - name: Boris Cherny\n    github: bcherny\n"
    p.write_text(original, encoding="utf-8")
    dr.append_to_roster(dr.roster_entry(dr.Request("simonw", "S", 42), today="2026-09-05"), p)
    after = p.read_text(encoding="utf-8")
    assert after.startswith(original)
    assert "github: simonw" in after


def test_the_appended_entry_is_loadable_and_lands_in_the_pool_but_not_the_sources(tmp_path):
    # The whole contract in one assertion pair: the roster loader sees them, and
    # `active()` — which is what feeds sources.yaml — does not.
    from cerebro.gitintel.roster import active, load_roster

    p = tmp_path / "cracked_devs.yaml"
    p.write_text(
        "version: 1\nwiring:\n  enabled: true\n  max_tier: 2\ndefaults:\n  tier: 2\ndevs:\n"
        "  - name: Boris Cherny\n    tier: 1\n    github: bcherny\n",
        encoding="utf-8",
    )
    dr.append_to_roster(dr.roster_entry(dr.Request("simonw", "S", 42), today="2026-09-05"), p)

    devs, wiring = load_roster(p)
    assert [d.github for d in devs] == ["bcherny", "simonw"]
    assert [d.github for d in active(devs, wiring)] == ["bcherny"]


# ——— the entry point, end to end ———


def _run_main(monkeypatch, tmp_path, *, body_text, author, account=USER):
    roster = tmp_path / "cracked_devs.yaml"
    roster.write_text(
        "version: 1\nwiring:\n  enabled: true\n  max_tier: 2\ndefaults:\n  tier: 2\ndevs:\n"
        "  - name: Boris Cherny\n    tier: 1\n    github: bcherny\n",
        encoding="utf-8",
    )
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    monkeypatch.setattr(dr, "_probe", lambda login: account)
    monkeypatch.setenv("CEREBRO_ROSTER", str(roster))
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("ISSUE_BODY", body_text)
    monkeypatch.setenv("ISSUE_AUTHOR", author)
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    code = dr.main()
    return code, roster.read_text(encoding="utf-8"), out.read_text(encoding="utf-8")


def test_main_appends_and_reports_added(monkeypatch, tmp_path):
    code, roster, out = _run_main(monkeypatch, tmp_path, body_text=body("simonw"), author="simonw")
    assert code == 0
    assert "github: simonw" in roster
    assert "status<<" in out and "added" in out


def test_main_refuses_and_writes_nothing(monkeypatch, tmp_path):
    code, roster, out = _run_main(monkeypatch, tmp_path, body_text=body("simonw"), author="mallory")
    assert code == 2
    assert "simonw" not in roster
    assert "refused" in out


def test_main_writes_outputs_a_newline_cannot_escape(monkeypatch, tmp_path):
    # A refusal reason is partly the requester's own string. With `k=v` output syntax a
    # newline in it would forge a second output; the heredoc delimiter is what stops that.
    code, _roster, out = _run_main(
        monkeypatch, tmp_path, body_text=body("not a login\nstatus=added"), author="mallory"
    )
    assert code == 2
    assert out.count("status<<") == 1
    assert "\nstatus=added\n" not in out.replace("reason<<", "")
