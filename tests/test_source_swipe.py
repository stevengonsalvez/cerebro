from types import SimpleNamespace

from cerebro.sources import swipe


ISSUES = """# Issues
1.  [
    August 19, 2026
    fix tests that don't test anything
    Keep tests useful.
    ](https://swipe.md/issues/the-tests-that-dont-test-anything)
"""
TOOLS = """# Useful AI tools
1.  [Agent interface design
    ## AIcss
    Add thinking states.
    ](https://swipe.md/tools/aicss)
"""


def test_fetches_bounded_issue_and_tool_signals(monkeypatch):
    pages = {"https://swipe.md/issues.md": ISSUES, "https://swipe.md/tools.md": TOOLS}
    monkeypatch.setattr(swipe, "http_get", lambda url: SimpleNamespace(text=pages[url]))

    sigs = swipe.fetch({}, SimpleNamespace())

    assert [(s.source, s.title, s.meta["kind"]) for s in sigs] == [
        ("swipe", "Swipe: fix tests that don't test anything", "issue"),
        ("swipe", "Swipe: AIcss", "tool"),
    ]
    assert sigs[0].meta["published"] == "August 19, 2026"
    assert sigs[1].meta["category"] == "Agent interface design"
