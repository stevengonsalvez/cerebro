"""F069c — `cerebro devs-contract`: three exit codes, two page texts, no pipeline.

THE EXIT CODES ARE THE FEATURE. Today a moved column and a dead endpoint both reach an
operator as "UNREACHABLE", so the first thing they do at 07:05 is open a status page for a
service that is answering perfectly. 3 means the query no longer fits the table; 4 means
the endpoint could not be reached. The page text says the same thing in words.

The check NEVER gates `devs-refresh`. It is an advisory that pages; the refresh has its own
degradation path, and a preflight that blocked the run would turn a ClickHouse hiccup into
a self-inflicted outage.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cerebro import config
from cerebro.__main__ import main
from cerebro.gitintel import contract
from cerebro.gitintel.gharchive import GHArchiveContractError, GHArchiveUnavailable

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def cli(monkeypatch, capsys, tmp_path):
    settings = SimpleNamespace(vault_path=tmp_path, dry_run=True, sources={},
                               github={"cache_path": ":memory:"}, ntfy_topic="t")
    monkeypatch.setattr(config, "load", lambda **kw: settings)
    import cerebro.__main__ as main_mod
    monkeypatch.setattr(main_mod, "load", lambda **kw: settings, raising=False)

    pages: list[str] = []
    from cerebro.sink import notify
    monkeypatch.setattr(notify, "push_failure", lambda msg, s: pages.append(msg))

    def run(*argv):
        old = sys.argv
        sys.argv = ["cerebro", "devs-contract", *argv]
        code = 0
        try:
            main()
        except SystemExit as exc:
            code = exc.code or 0
        finally:
            sys.argv = old
        text = capsys.readouterr().out
        payload = json.loads(text[text.index("{"):]) if "{" in text else {}
        return code, payload

    return SimpleNamespace(run=run, pages=pages, settings=settings,
                           monkeypatch=monkeypatch)


def test_a_healthy_schema_exits_zero_and_names_what_it_checked(cli):
    code, payload = cli.run("--offline", str(FIX / "gharchive_describe.tsv"))
    assert code == 0
    assert payload["ok"] is True
    assert payload["columns_checked"] == ["actor_login", "repo_name", "created_at",
                                          "event_type"]
    assert payload["enum_member"] == "PushEvent"
    assert payload["drift"] == []


def test_a_moved_column_exits_three_and_names_the_column(cli):
    code, payload = cli.run("--offline", str(FIX / "gharchive_describe_missing_actor.tsv"))
    assert code == 3
    assert [d["subject"] for d in payload["drift"]] == ["actor_login"]


def test_an_enum_that_lost_pushevent_exits_three(cli):
    code, payload = cli.run(
        "--offline", str(FIX / "gharchive_describe_enum_lost_pushevent.tsv"))
    assert code == 3
    assert [d["subject"] for d in payload["drift"]] == ["event_type"]


def test_a_healthy_schema_pages_nobody_even_on_the_live_install(cli):
    """A page on a good morning is a page an operator mutes."""
    cli.settings.dry_run = False
    code, _ = cli.run("--offline", str(FIX / "gharchive_describe.tsv"))
    assert code == 0 and cli.pages == []


def test_drift_pages_once_with_the_drift_text(cli):
    cli.settings.dry_run = False
    code, _ = cli.run("--offline", str(FIX / "gharchive_describe_missing_actor.tsv"))
    assert code == 3
    assert len(cli.pages) == 1
    assert "CONTRACT DRIFT" in cli.pages[0] and "actor_login" in cli.pages[0]
    assert "UNREACHABLE" not in cli.pages[0]


def test_an_unreachable_endpoint_exits_four_with_a_different_text(cli):
    cli.settings.dry_run = False
    cli.monkeypatch.setattr(contract, "run_check", _raise(GHArchiveUnavailable(
        "transport failed: connection refused")))
    code, payload = cli.run()
    assert code == 4
    assert payload["failure"] == "unreachable"
    assert len(cli.pages) == 1
    assert "UNREACHABLE" in cli.pages[0] and "CONTRACT DRIFT" not in cli.pages[0]


def test_a_contract_error_raised_by_the_transport_exits_three(cli):
    cli.settings.dry_run = False
    cli.monkeypatch.setattr(contract, "run_check", _raise(GHArchiveContractError(
        "clickhouse contract error: Code: 47 ...")))
    code, payload = cli.run()
    assert code == 3
    assert payload["failure"] == "contract"
    assert "CONTRACT DRIFT" in cli.pages[0]


def test_the_two_failures_produce_two_different_exit_codes_and_two_texts(cli):
    """Stated as one assertion because it is the whole feature."""
    cli.settings.dry_run = False
    cli.monkeypatch.setattr(contract, "run_check", _raise(GHArchiveContractError("x")))
    drift_code, _ = cli.run()
    cli.monkeypatch.setattr(contract, "run_check", _raise(GHArchiveUnavailable("y")))
    down_code, _ = cli.run()
    assert drift_code != down_code == 4
    assert len(cli.pages) == 2
    assert cli.pages[0] != cli.pages[1]


def test_a_dev_checkout_never_pages(cli):
    """dry_run is the "is this a dev checkout" question here: the stage writes nothing
    anywhere, so it is the only thing that flag can mean."""
    cli.settings.dry_run = True
    code, _ = cli.run("--offline", str(FIX / "gharchive_describe_missing_actor.tsv"))
    assert code == 3 and cli.pages == []


def test_alerting_never_becomes_the_failure(cli):
    from cerebro.sink import notify

    def explode(*a, **k):
        raise OSError("curl: command not found")

    cli.monkeypatch.setattr(notify, "push_failure", explode)
    cli.settings.dry_run = False
    code, _ = cli.run("--offline", str(FIX / "gharchive_describe_missing_actor.tsv"))
    assert code == 3


def test_the_command_never_reaches_the_orchestrator(cli):
    def explode(*a, **k):
        raise AssertionError("the orchestrator ran from a contract check")

    cli.monkeypatch.setattr("cerebro.orchestrator.run", explode, raising=False)
    assert cli.run("--offline", str(FIX / "gharchive_describe.tsv"))[0] == 0


def test_the_offline_flag_makes_no_query(cli):
    def explode(sql):
        raise AssertionError("the offline path went to the network")

    cli.monkeypatch.setattr("cerebro.gitintel.gharchive._http_post", explode)
    code, payload = cli.run("--offline", str(FIX / "gharchive_describe.tsv"))
    assert code == 0 and payload["queries"] == 0


def _raise(exc):
    def boom(*a, **k):
        raise exc
    return boom
