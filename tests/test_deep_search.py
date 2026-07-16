from __future__ import annotations

from cerebro.gitintel.deep_search import deep_search


def test_deep_search_emits_result(monkeypatch):
    monkeypatch.setattr(
        "cerebro.gitintel.deep_search.search_github",
        lambda *a, **k: {"stages": [{"stage": "ranking"}], "repositories": [{"full_name": "x/y"}]},
    )

    stages = list(deep_search("x"))

    assert stages[0]["stage"] == "query_plan"
    assert stages[-1]["stage"] == "result"
    assert stages[-1]["result"]["repositories"][0]["full_name"] == "x/y"
