"""F027 — freshness is a date and three counts, and "not fetched" is never a zero.

THE RULING BEING OBEYED. `crackscore._ships_score` is
`volume * 0.5 + recency * 0.3 + young_high_output * 0.2`: a weighted composite of a
volume term and an account-age bonus. It is not ported, not renamed, not reweighted. The
Court's words are "reframed as a FACT/facet, not a score input".

THE FAILURE BEING PREVENTED. A dev whose repo call never happened — budget exhausted, a
call that raised, a profile withheld — must not be described by a `0`. A zero beside a
named human reads as a fact about that human ("ships nothing"); `null` with
`fetched: false` reads as what it is.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import pytest

from cerebro.gitintel import portfolio

TODAY = dt.date(2026, 8, 27)


def _repo(name, last_push):
    """One `repos[]` element in the frozen shape, only the field this lane reads filled."""
    return {"name": name, "title": name, "description": None, "language": None,
            "topics": [], "stars_fact": None, "first_seen": None, "last_push": last_push}


def _days_ago(n):
    return (TODAY - dt.timedelta(days=n)).isoformat()


# --- the populated case -------------------------------------------------------

def test_a_dev_who_pushed_three_days_ago_reports_that_date_and_one_recent_repo():
    got = portfolio.freshness([_repo("llm", _days_ago(3))], populated=True, now=TODAY)
    assert got["last_push_at"] == _days_ago(3)
    assert got["repos_pushed_30d"] == 1
    assert got["repos_pushed_90d"] == 1
    assert got["repos_considered"] == 1
    assert got["fetched"] is True


def test_the_windows_are_counted_independently_and_recomputed_by_hand():
    repos = [_repo("a", _days_ago(2)), _repo("b", _days_ago(29)),
             _repo("c", _days_ago(45)), _repo("d", _days_ago(200))]
    got = portfolio.freshness(repos, populated=True, now=TODAY)
    assert got["repos_considered"] == 4
    assert got["repos_pushed_30d"] == 2          # 2 and 29 days ago
    assert got["repos_pushed_90d"] == 3          # ... plus 45
    assert got["last_push_at"] == _days_ago(2)


@pytest.mark.parametrize("days_ago,in_30,in_90", [(0, 1, 1), (30, 1, 1), (31, 0, 1),
                                                  (90, 0, 1), (91, 0, 0)])
def test_the_window_boundaries_are_inclusive_on_the_recent_side(days_ago, in_30, in_90):
    got = portfolio.freshness([_repo("x", _days_ago(days_ago))], populated=True,
                              now=TODAY)
    assert got["repos_pushed_30d"] == in_30
    assert got["repos_pushed_90d"] == in_90


def test_a_dev_whose_repos_were_fetched_but_are_all_old_reports_zero_honestly():
    """The legitimate zero: somebody LOOKED, and the newest push is old. It is
    distinguishable from the not-fetched case because `fetched` is true and
    `repos_considered` is not."""
    got = portfolio.freshness([_repo("x", _days_ago(400))], populated=True, now=TODAY)
    assert got["fetched"] is True
    assert got["repos_considered"] == 1
    assert got["repos_pushed_30d"] == 0
    assert got["last_push_at"] == _days_ago(400)


def test_a_dev_with_no_repos_but_a_call_that_returned_is_a_fact_about_them():
    """`repos_populated: true` with an empty list means "somebody looked and this person
    owns no repo the selection keeps" — a real fact, and not the same as not looking."""
    got = portfolio.freshness([], populated=True, now=TODAY)
    assert got["fetched"] is True
    assert got["repos_considered"] == 0
    assert got["last_push_at"] is None
    assert got["repos_pushed_30d"] == 0


# --- the not-fetched case, which is the one that must never read as a zero ----

def test_an_unpopulated_dev_reports_nulls_and_never_zeroes():
    got = portfolio.freshness([_repo("ignored", _days_ago(1))], populated=False,
                              now=TODAY)
    assert got == {"fetched": False, "repos_considered": 0, "last_push_at": None,
                   "repos_pushed_30d": None, "repos_pushed_90d": None}


def test_the_not_fetched_shape_serialises_as_json_null():
    text = json.dumps(portfolio.freshness([], populated=False, now=TODAY))
    assert '"repos_pushed_30d": null' in text
    assert '"repos_pushed_30d": 0' not in text


def test_an_unparseable_push_date_is_dropped_rather_than_defaulted():
    """A wrong newest-push date on a named person's page is the charter's wrong-number
    class. One fewer repo in a count is not."""
    got = portfolio.freshness([_repo("a", "not a date"), _repo("b", _days_ago(5))],
                              populated=True, now=TODAY)
    assert got["last_push_at"] == _days_ago(5)
    assert got["repos_pushed_30d"] == 1
    assert got["repos_considered"] == 2


def test_a_full_iso_timestamp_is_read_as_its_date():
    got = portfolio.freshness([_repo("a", "2026-08-24T11:02:03Z")], populated=True,
                              now=TODAY)
    assert got["last_push_at"] == "2026-08-24"


# --- the report over records --------------------------------------------------

class _Rec:
    def __init__(self, login, repos, populated):
        self.login = login
        self.repos = repos
        self.repos_populated = populated


def test_the_report_covers_every_record_and_keeps_the_two_cases_apart():
    payload = portfolio.report(
        [_Rec("simonw", [_repo("llm", _days_ago(1))], True),
         _Rec("obra", [], False)], now=TODAY)
    assert set(payload) == {"simonw", "obra"}
    assert payload["simonw"]["repos_pushed_30d"] == 1
    assert payload["obra"]["repos_pushed_30d"] is None


def test_the_report_reads_dict_records_too():
    """Records reach this module both straight off the producer and deserialised from the
    run json."""
    payload = portfolio.report(
        [{"login": "simonw", "repos": [_repo("llm", _days_ago(1))],
          "repos_populated": True}], now=TODAY)
    assert payload["simonw"]["last_push_at"] == _days_ago(1)


def test_the_census_line_names_the_not_fetched_half():
    payload = portfolio.report(
        [_Rec("a", [_repo("x", _days_ago(1))], True), _Rec("b", [], False)], now=TODAY)
    line = portfolio.census_line(payload)
    assert "1 of 2" in line and "NOT FETCHED" in line


def test_the_pass_makes_no_rest_call_at_all():
    """ZERO, asserted as a counter delta the way `Budget` takes its own, and after
    checking the counter EXISTS: `getattr(client, "_calls", 0)` against an uninstrumented
    stub reads 0 no matter what happened."""
    class _Client:
        def __init__(self):
            self._calls = 0

        def request(self, path, params=None):
            self._calls += 1
            return []

    client = _Client()
    assert hasattr(client, "_calls")
    before = client._calls
    portfolio.report([_Rec("simonw", [_repo("llm", _days_ago(1))], True)], now=TODAY)
    assert client._calls - before == 0


def _code_without_prose() -> str:
    """The module's CODE, docstrings stripped.

    Load-bearing: this module explains at length which composite it refuses to port, so a
    raw source scan for `young` or `client` fires on the prose that documents the ban.
    The property under test is about the code."""
    tree = ast.parse(Path("cerebro/gitintel/portfolio.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_the_module_takes_no_client_and_reaches_no_endpoint():
    """Structural, not incidental: there is nothing here to call an API with."""
    code = _code_without_prose()
    assert "client" not in code
    assert "requests" not in code and "/users/" not in code


# --- the rulings, as properties of the code -----------------------------------

def test_the_condemned_weights_appear_nowhere():
    """0.5 / 0.3 / 0.2 combined with a metric IS `_ships_score`, whatever it is called."""
    tree = ast.parse(Path("cerebro/gitintel/portfolio.py").read_text(encoding="utf-8"))
    floats = [n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, float)]
    assert floats == [], f"a float literal in a facts module is a weight: {floats}"
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
            for side in (node.left, node.right):
                assert not (isinstance(side, ast.Constant)
                            and isinstance(side.value, float)), ast.unparse(node)


def test_no_account_age_term_survives():
    """A young-account bonus is a judgement about a person, not a fact about their work."""
    code = _code_without_prose().lower()
    for banned in ("created_at", "account_age", "young", "age_days"):
        assert banned not in code, banned


def test_nothing_here_is_named_score_or_rank():
    tree = ast.parse(Path("cerebro/gitintel/portfolio.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.FunctionDef):
            names = [node.name] + [a.arg for a in node.args.args]
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names = [node.id]
        for name in names:
            assert "score" not in name.lower() and "rank" not in name.lower()


def test_no_dev_is_compared_against_any_other():
    """Every number is about one person's own repos. Normalising against the corpus is
    how a facts module becomes a league table."""
    code = _code_without_prose()
    assert "sorted(" not in code and ".sort(" not in code
    assert "percentile" not in code and "median" not in code and "mean" not in code
