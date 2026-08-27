"""F059 — the token guard, one fixture per row of the decision table.

THE TWO WAYS TO GET THIS WRONG ARE OPPOSITE AND BOTH SILENT.

  1. A fine-grained token returns NO `x-oauth-scopes` header. A guard that reads an
     absent header as "unknown -> fail" fails the very token the rotation produces, so
     the first green morning after the rotation is a red one and somebody rolls back.
  2. An UNAUTHENTICATED `GET /rate_limit` returns 200 with a core limit of 60. A guard
     that reads 200 as "a token was sent" passes silently on the morning after a rotation
     that never reached the environment — and the pipeline then runs unauthenticated at
     60 calls/hour, which looks like a rate-limit incident rather than a missing secret.

Both are decided before the request, and both are a row below.

REDACTION IS TESTED, NOT PROMISED. The last case runs the real CLI with a known value in
the environment and greps every byte of stdout and stderr for it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cerebro import config
from cerebro.__main__ import main
from cerebro.gitintel import token_check
from cerebro.gitintel.token_check import (
    ALLOWED_SCOPES,
    EXIT_NO_TOKEN,
    EXIT_OK,
    EXIT_OVERSCOPED,
    check,
)

#: The scope set the xyora PAT actually carries, measured. This is the string the guard
#: exists to fail on.
XYORA_SCOPES = "admin:enterprise, admin:org, repo, workflow, delete:packages"

FAKE_TOKEN = "ghp_fake000000000000000000000000000000"  # noqa: S105 — a fixture, not a secret


def _transport(status=200, headers=None, calls=None):
    def send(value):
        if calls is not None:
            calls.append(value)
        return status, (headers if headers is not None else {})
    return send


# --- the table ----------------------------------------------------------------

def test_an_unset_token_exits_six_and_never_makes_a_request():
    """DECIDED BEFORE THE CALL. An unauthenticated /rate_limit answers 200, so asking the
    network first would turn "no token reached the process" into a green run."""
    calls: list[str] = []
    report = check("", _transport(calls=calls))
    assert report.exit_code == EXIT_NO_TOKEN
    assert calls == [], "the transport was called with no token"
    assert report.called is False
    assert "no token" in report.reason


def test_a_none_token_is_the_same_case():
    calls: list[str] = []
    assert check(None, _transport(calls=calls)).exit_code == EXIT_NO_TOKEN
    assert calls == []


def test_a_fine_grained_token_has_no_scopes_header_and_exits_zero():
    """THE ROTATION'S TARGET STATE. The header is ABSENT, not empty, and absence here
    means "no classic scope exists" rather than "unknown"."""
    report = check(FAKE_TOKEN, _transport(200, {"x-ratelimit-limit": "5000"}))
    assert report.exit_code == EXIT_OK
    assert report.header_present is False
    assert report.scopes == ()
    assert "fine-grained" in report.reason


def test_a_classic_token_with_an_empty_scopes_header_exits_zero():
    report = check(FAKE_TOKEN, _transport(200, {"x-oauth-scopes": ""}))
    assert report.exit_code == EXIT_OK
    assert report.header_present is True
    assert report.scopes == ()


def test_a_classic_token_inside_the_allowed_set_exits_zero():
    report = check(FAKE_TOKEN, _transport(200, {"x-oauth-scopes": "public_repo"}))
    assert report.exit_code == EXIT_OK
    assert report.scopes == ("public_repo",)


def test_the_token_in_use_today_exits_five_and_names_every_offending_scope():
    """THE EPIC'S PROOF THAT THE SECURITY FINDING IS MECHANICAL, NOT RECALLED."""
    report = check(FAKE_TOKEN, _transport(200, {"x-oauth-scopes": XYORA_SCOPES}))
    assert report.exit_code == EXIT_OVERSCOPED
    for scope in ("admin:enterprise", "admin:org", "repo", "workflow",
                  "delete:packages"):
        assert scope in report.reason, scope
    assert "over-scoped" in report.reason


@pytest.mark.parametrize("scope", ["repo", "admin:org", "workflow", "delete:packages",
                                   "write:packages", "gist"])
def test_any_single_scope_outside_the_allowed_set_fails(scope):
    report = check(FAKE_TOKEN, _transport(200, {"x-oauth-scopes": scope}))
    assert report.exit_code == EXIT_OVERSCOPED
    assert scope in report.reason


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_credential_exits_five(status):
    report = check(FAKE_TOKEN, _transport(status, {}))
    assert report.exit_code == EXIT_OVERSCOPED
    assert str(status) in report.reason


def test_an_unexpected_status_is_not_silently_green():
    report = check(FAKE_TOKEN, _transport(500, {}))
    assert report.exit_code == EXIT_OVERSCOPED


def test_the_header_is_read_case_insensitively():
    report = check(FAKE_TOKEN, _transport(200, {"X-OAuth-Scopes": "repo"}))
    assert report.header_present is True and report.exit_code == EXIT_OVERSCOPED


def test_the_allowed_set_is_public_read_only():
    assert ALLOWED_SCOPES == {"public_repo"}
    for banned in ("repo", "admin:org", "workflow", "delete:packages"):
        assert banned not in ALLOWED_SCOPES


def test_the_two_failures_have_two_exit_codes():
    """Rotate versus "the env var did not reach the process" are different remedies."""
    assert EXIT_OVERSCOPED != EXIT_NO_TOKEN
    assert (EXIT_OK, EXIT_OVERSCOPED, EXIT_NO_TOKEN) == (0, 5, 6)


# --- the value never appears anywhere -----------------------------------------

def test_the_report_carries_a_fingerprint_and_not_the_value():
    report = check(FAKE_TOKEN, _transport(200, {"x-oauth-scopes": XYORA_SCOPES}))
    payload = json.dumps(report.to_dict())
    assert FAKE_TOKEN not in payload
    assert report.fingerprint and len(report.fingerprint) == 8
    assert report.fingerprint in payload


def test_the_fingerprint_distinguishes_two_tokens_across_a_rotation():
    old = check("old-value", _transport(200, {})).fingerprint
    new = check("new-value", _transport(200, {})).fingerprint
    assert old and new and old != new


def test_the_summary_line_prints_names_and_never_a_value():
    report = check(FAKE_TOKEN, _transport(200, {"x-oauth-scopes": XYORA_SCOPES}))
    line = token_check.summary_line(report)
    assert FAKE_TOKEN not in line
    assert "admin:org" in line and "sha256:" in line


def test_the_module_never_interpolates_the_value_into_a_log_line():
    """The only place the value may appear is the Authorization header it is sent in."""
    import ast

    src = Path("cerebro/gitintel/token_check.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = ast.unparse(node)
        if "Bearer" in text:
            continue                       # the request itself
        assert "value" not in text, f"a token value reaches a formatted string: {text}"
    # And it never prints at all: the CLI does the printing, from the redacted report.
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "print", "the module prints; only the CLI may"


# --- the CLI, and the redaction proven end to end ------------------------------

@pytest.fixture
def cli(monkeypatch, capsys, tmp_path):
    settings = SimpleNamespace(vault_path=tmp_path, dry_run=True,
                               sources={"crackscan": {"token_env": "GITHUB_TOKEN_TEST"}},
                               github={"cache_path": ":memory:"}, ntfy_topic="t")
    monkeypatch.setattr(config, "load", lambda **kw: settings)
    import cerebro.__main__ as main_mod
    monkeypatch.setattr(main_mod, "load", lambda **kw: settings, raising=False)

    pages: list[str] = []
    from cerebro.sink import notify
    monkeypatch.setattr(notify, "push_failure", lambda msg, s: pages.append(msg))

    def run():
        old = sys.argv
        sys.argv = ["cerebro", "devs-token-check"]
        code = 0
        try:
            main()
        except SystemExit as exc:
            code = exc.code or 0
        finally:
            sys.argv = old
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return SimpleNamespace(run=run, pages=pages, settings=settings,
                           monkeypatch=monkeypatch)


def test_the_cli_exits_six_when_the_env_var_is_unset(cli, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN_TEST", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code, out, _err = cli.run()
    assert code == EXIT_NO_TOKEN
    assert json.loads(out[out.index("{"):out.index("}") + 1])["exit_code"] == 6


def test_the_cli_exits_five_and_pages_against_an_over_scoped_token(cli, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN_TEST", FAKE_TOKEN)
    cli.settings.dry_run = False
    cli.monkeypatch.setattr(token_check, "_probe",
                            _transport(200, {"x-oauth-scopes": XYORA_SCOPES}))
    code, out, _err = cli.run()
    assert code == EXIT_OVERSCOPED
    assert len(cli.pages) == 1
    assert "admin:org" in cli.pages[0]
    assert FAKE_TOKEN not in cli.pages[0] and FAKE_TOKEN not in out


def test_the_cli_exits_zero_and_pages_nobody_for_a_fine_grained_token(cli, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN_TEST", FAKE_TOKEN)
    cli.settings.dry_run = False
    cli.monkeypatch.setattr(token_check, "_probe", _transport(200, {}))
    code, _out, _err = cli.run()
    assert code == EXIT_OK and cli.pages == []


def test_the_value_appears_in_no_byte_of_the_cli_output(cli, monkeypatch):
    """THE REDACTION GATE. The variable is asserted non-empty first: an unset one makes
    the search pass vacuously, which is the same class of hollow proof as diffing an
    empty directory against an empty directory."""
    assert FAKE_TOKEN
    monkeypatch.setenv("GITHUB_TOKEN_TEST", FAKE_TOKEN)
    cli.monkeypatch.setattr(token_check, "_probe",
                            _transport(200, {"x-oauth-scopes": XYORA_SCOPES}))
    _code, out, err = cli.run()
    assert out.strip(), "nothing was printed, so the search proves nothing"
    assert FAKE_TOKEN not in out
    assert FAKE_TOKEN not in err
    assert "sha256:" in out


def test_the_cli_never_reaches_the_orchestrator(cli, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN_TEST", FAKE_TOKEN)
    cli.monkeypatch.setattr("cerebro.orchestrator.run", _explode, raising=False)
    cli.monkeypatch.setattr(token_check, "_probe", _transport(200, {}))
    assert cli.run()[0] == EXIT_OK


def _explode(*a, **k):
    raise AssertionError("the orchestrator ran from a token check")
