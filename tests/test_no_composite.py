"""T13 — F020/F021 turned into a build failure.

The Court's rulings are not style preferences and are not enforceable by review alone.
NO COMPOSITE SCORE ANYWHERE and NO VOLUME RANKING are properties of the code, so they
are asserted against the code.

The empirical case, restated because a future editor will meet it before the ruling:
ranking GH Archive by event volume is INVERTED, not merely noisy. Top-5 by raw 7d
PushEvent is github-actions[bot] at 634k, an automation account at 29.8k, renovate[bot],
swa-runner-app[bot], pull[bot]. Meanwhile simonw is 53 pushes over 22 repos in 30 days.
A volume leaderboard ranks spam about 30x above Simon Willison. And every distribution
measured is CONTINUOUS at its interesting point (14.52 and 14.45 immediately below the
15 line, 25.85 immediately above), so any composite threshold is a knife-edge that moves
a named person across the line on noise.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

MODULES = [
    "cerebro/gitintel/admission.py",
    "cerebro/gitintel/shape.py",
    "cerebro/gitintel/devs_spike.py",
    "cerebro/gitintel/gharchive.py",
    "cerebro/gitintel/vault_seed.py",
    "cerebro/gitintel/denylist.py",
    # owner_resolve is the one module in the lane that legitimately READS followers and
    # public_repos, as a coarse presence pre-filter (the F011 ruling, the committers.top
    # precedent). Reading them is permitted; sorting or ranking people by them is not,
    # and the difference is exactly what this sweep tests. It grows a fan-out path in
    # e02, which is when a "rank the contributors by followers" line would arrive.
    "cerebro/gitintel/owner_resolve.py",
]

VOLUME_NAMES = {"pushes", "followers", "stars", "score", "distinct_repos",
                "public_repos", "stargazers_count", "portfolio_momentum"}

BANNED_IMPORTS = {"crackscore", "metrics", "rank"}


def _tree(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", MODULES)
def test_no_module_level_weight_map(path):
    """A dict literal mapping metric names to floats IS the composite, whatever it is
    called. WEIGHTS = {commit .35, follower .25, portfolio .25, ships .15} is the exact
    shape being outlawed."""
    for node in _tree(path).body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Dict) or not node.value.keys:
            continue
        keys_are_metric_names = all(
            isinstance(k, ast.Constant) and isinstance(k.value, str)
            for k in node.value.keys)
        values_are_floats = all(
            isinstance(v, ast.Constant) and isinstance(v.value, float)
            for v in node.value.values)
        assert not (keys_are_metric_names and values_are_floats), \
            f"{path}: a name->float map is a weight table"


@pytest.mark.parametrize("path", MODULES)
def test_no_sort_key_touches_a_volume_field(path):
    """Ordering is a facet sort on consistency. Nothing sorts people by volume."""
    for node in ast.walk(_tree(path)):
        is_sort = (isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == "sorted")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "sort")))
        if not is_sort:
            continue
        for sub in ast.walk(node):
            name = None
            if isinstance(sub, ast.Attribute):
                name = sub.attr
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                name = sub.value
            if name in VOLUME_NAMES:
                raise AssertionError(f"{path}: sort key touches {name}")


@pytest.mark.parametrize("path", MODULES)
def test_no_module_imports_the_condemned_scorer(path):
    imported = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").lstrip("."))
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    assert not (imported & BANNED_IMPORTS), \
        f"{path}: imports {imported & BANNED_IMPORTS}"


@pytest.mark.parametrize("path", MODULES)
def test_no_identifier_is_named_score_or_rank(path):
    """A single ranking number cannot exist even under a euphemism."""
    for node in ast.walk(_tree(path)):
        names = []
        if isinstance(node, ast.FunctionDef):
            names = [node.name] + [a.arg for a in node.args.args]
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names = [node.id]
        elif isinstance(node, ast.ClassDef):
            names = [node.name]
        for n in names:
            low = n.lower()
            assert "score" not in low, f"{path}: `{n}` — no single ranking number exists"
            assert not low.endswith("rank") and "ranking" not in low, \
                f"{path}: `{n}` — no league table exists"


def test_admission_has_no_arithmetic_combining_two_metrics():
    """The floors are independent: each fails on its own predicate and says which. A
    binary op over two different metric attributes would be a composite by another name."""
    from cerebro.gitintel import admission
    src = Path("cerebro/gitintel/admission.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "admit")
    def touches_candidate(node):
        return any(isinstance(n, ast.Name) and n.id == "candidate"
                   for n in ast.walk(node))

    for node in ast.walk(fn):
        # String concatenation while building the per-floor reasons is fine; combining
        # two CANDIDATE METRICS with an operator is the composite being outlawed.
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
            assert not (touches_candidate(node.left) and touches_candidate(node.right)), \
                "admit() combines two candidate metrics arithmetically"
    assert set(admission.Admission.__dataclass_fields__) == \
        {"admitted", "low_n", "automation", "reasons"}


def test_the_three_floors_are_reported_separately_not_summed():
    from cerebro.gitintel.admission import Candidate, admit
    a = admit(Candidate(login="x", signal_hashes=(), active_days_90d=0,
                        automation="flagged"))
    assert len(a.reasons) == 3
    assert a.admitted is False
    # all three failures are individually legible, not collapsed into one number
    assert "provenance" in a.reasons[0] and "FAIL" in a.reasons[0]
    assert "low-n" in a.reasons[1]
    assert "FLAGGED" in a.reasons[2]
