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
    # e02's four new lane modules. THE SWEEP IS EXTENDED, NEVER WEAKENED: every rule
    # above now runs against the fan-out lane, the pool assembler, the fork-provenance
    # lane and the facet module, because each is a place a "rank the contributors by
    # commit count" line could arrive and look reasonable.
    "cerebro/gitintel/fanout.py",
    "cerebro/gitintel/pool.py",
    "cerebro/gitintel/fork_provenance.py",
    "cerebro/gitintel/facets.py",
    # e03's three. The sweep is EXTENDED, NEVER WEAKENED. `repo_facts.py` is where a
    # "keep the most-starred repos" line would arrive and look entirely reasonable, and
    # `sink/devs.py` is the last thing between a record and a public repository.
    "cerebro/gitintel/optout.py",
    "cerebro/gitintel/repo_facts.py",
    "cerebro/sink/devs.py",
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



# --- e02: the lanes that could smuggle volume back in ------------------------

def _body_source(fn) -> str:
    """A function's source with its DOCSTRING removed.

    Load-bearing: these modules explain at length that no score exists and that volume
    ordering is banned, so a raw source scan for the word "score" fires on the prose that
    documents the ban. The property being tested is about the CODE."""
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)):
        node.body = node.body[1:]
    return ast.unparse(tree)

DEVS_LANE_DATACLASS_MODULES = [
    "cerebro/gitintel/fanout.py",
    "cerebro/gitintel/pool.py",
    "cerebro/gitintel/fork_provenance.py",
    "cerebro/gitintel/facets.py",
    "cerebro/gitintel/devs_spike.py",
    "cerebro/gitintel/optout.py",
    "cerebro/gitintel/repo_facts.py",
    "cerebro/sink/devs.py",
]

BANNED_FIELDS = {"contributions", "followers", "stars", "stargazers_count",
                 "contribution_count", "watchers", "watchers_count", "forks_count"}


@pytest.mark.parametrize("path", DEVS_LANE_DATACLASS_MODULES)
def test_no_dataclass_in_the_devs_lane_declares_a_volume_field(path):
    """THE LEAK CHECK THAT MATTERS, AND IT INSPECTS THE DECLARATION.

    GitHub hands the fan-out lane a commit count on every contributor and the
    contributors page IS a volume ranking. The count is dropped at the boundary, and the
    only durable way to keep it dropped is for no dataclass downstream to have anywhere
    to put it. A runtime probe over the returned logins would be `False` for every
    conceivable implementation, including a broken one, and would validate nothing."""
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            name = None
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
            elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                    and isinstance(stmt.targets[0], ast.Name):
                name = stmt.targets[0].id
            if name and name.lower() in BANNED_FIELDS:
                raise AssertionError(f"{path}: {node.name}.{name} is a volume field")


def test_order_by_consistency_is_still_the_only_ordering_over_people():
    """e02 adds THREE lanes and ZERO ordering functions over people. Every new `sorted(`
    in the diff orders logins alphabetically, repos by signal recurrence, or window keys
    — never people by a magnitude."""
    import inspect

    from cerebro.gitintel import admission, facets, fanout, fork_provenance, pool
    orderings = []
    for mod in (admission, fanout, pool, fork_provenance, facets):
        for name, fn in vars(mod).items():
            if name.startswith("_") or not inspect.isfunction(fn):
                continue
            if getattr(fn, "__module__", "") != mod.__name__:
                continue
            src = _body_source(fn)
            if "sorted(" in src or ".sort(" in src:
                orderings.append(f"{mod.__name__}.{name}")
    # Everything that sorts, and what it sorts, accounted for by name:
    #   admission.order_by_consistency  people, by active days   <- THE ONLY ONE
    #   fanout.contributors             logins, alphabetically
    #   fanout.work_queue               repos, by signal recurrence
    #   fanout.fanout_lane              logins + repo names, alphabetically
    #   pool.roster_lane                entries + skips, by key and by name
    #   pool.assemble                   the output pool, by identity key
    #   pool.paid_prefilter             work order, then results by key
    #   fork_provenance.sample_repos    repo names, alphabetically
    #   fork_provenance.evidence        upstream names, alphabetically
    expected = {
        "cerebro.gitintel.admission.order_by_consistency",
        "cerebro.gitintel.fanout.contributors",
        "cerebro.gitintel.fanout.work_queue",
        "cerebro.gitintel.fanout.fanout_lane",
        "cerebro.gitintel.pool.roster_lane",
        "cerebro.gitintel.pool.assemble",
        "cerebro.gitintel.pool.paid_prefilter",
        "cerebro.gitintel.fork_provenance.sample_repos",
        "cerebro.gitintel.fork_provenance.evidence",
    }
    assert set(orderings) == expected, (
        "a sort appeared or vanished in the devs lane. Every one must be accounted for "
        "by name here, with what it orders: "
        f"unexpected={set(orderings) - expected} missing={expected - set(orderings)}")


def test_the_only_ordering_over_people_reads_only_active_days():
    """Consistency, never volume. `order_by_consistency` must not learn to read pushes."""
    import inspect

    from cerebro.gitintel.admission import order_by_consistency
    src = _body_source(order_by_consistency)
    for banned in VOLUME_NAMES:
        assert banned not in src, f"order_by_consistency reads {banned}"
    assert "active_days_90d" in src and "active_days_30d" in src


def test_the_fanout_lane_destroys_the_api_ordering_whatever_it_receives():
    """A fixture in GitHub's real commit-count order (measured on simonw/llm: 1170, 10,
    5, 5, 4) must come back alphabetical."""
    from cerebro.gitintel.fanout import contributors

    class _Cl:
        def request(self, path, params=None):
            return [{"login": "zed", "type": "User", "contributions": 1170},
                    {"login": "Mallory", "type": "User", "contributions": 10},
                    {"login": "alice", "type": "User", "contributions": 5},
                    {"login": "bob", "type": "User", "contributions": 4}]

    assert contributors("simonw/llm", _Cl()) == ("alice", "bob", "Mallory", "zed")


def test_the_recurrence_count_the_work_queue_sorts_on_reaches_no_record_field():
    """F063's licence is that recurrence orders WORK and never a person. The count must
    be unreachable from anything the run writes."""
    import dataclasses

    from cerebro.gitintel.devs_spike import DevRecord
    from cerebro.gitintel.fanout import FanoutCandidate
    from cerebro.gitintel.pool import Cand
    for dc in (FanoutCandidate, Cand, DevRecord):
        names = {f.name.lower() for f in dataclasses.fields(dc)}
        assert not (names & {"recurrence", "recurrence_count", "seed_rank", "priority"})


def test_no_volume_ranking_reached_the_record_or_the_facets():
    """F020/F021 asserted ABSENT, over the record e04 actually renders."""
    import dataclasses

    from cerebro.gitintel.devs_spike import DevRecord
    from cerebro.gitintel.facets import FACET_NAMES
    names = {f.name.lower() for f in dataclasses.fields(DevRecord)}
    assert not (names & BANNED_FIELDS)
    assert not any("score" in n or "rank" in n for n in names)
    assert not (set(FACET_NAMES) & BANNED_FIELDS)
