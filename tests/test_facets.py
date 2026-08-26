"""T12t — F023/F019 descriptive facets. No network.

The interesting assertions here are ABSENCES. This module exists to hold display facts,
and the way "you cannot rank people by a facet" is enforced is by the module containing
nothing capable of ranking: no ordering function, no threshold, no comparison between two
people. A test that only checked the arithmetic would miss the entire point.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from cerebro.gitintel import facets
from cerebro.gitintel.facets import FACET_NAMES, describe_breadth_and_depth, window_facets
from cerebro.gitintel.gharchive import WindowMetrics

SRC = Path("cerebro/gitintel/facets.py").read_text(encoding="utf-8")

# The real 90d cohort rows the F023 ruling was argued on.
SIMONW = WindowMetrics(window_days=90, pushes=309, distinct_repos=54, active_days=65,
                       repos_not_owned=13, not_owned_basenames=12, not_owned_owners=3,
                       max_basename_group=3)
T3 = WindowMetrics(window_days=90, pushes=90, distinct_repos=2, active_days=45,
                   repos_not_owned=1, not_owned_basenames=1, not_owned_owners=1,
                   max_basename_group=2)


# --- the module has nothing capable of ranking ------------------------------

def test_the_module_defines_zero_ordering_functions():
    """F023's ruling is that a 54-repo generalist and a 2-repo deep-focus dev are BOTH
    valid shapes and neither folds into one axis. The safest place to enforce that is a
    module with nothing in it that can order people."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            assert name not in ("sorted", "sort", "max", "min", "nlargest", "nsmallest"), \
                f"facets.py calls {name}() — this module orders nothing"


def test_the_module_defines_zero_thresholds():
    """A module-level number compared against a metric IS a threshold, whatever it is
    called. There are no comparison operators over metric values here at all."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op in node.ops:
                assert not isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)), \
                    "facets.py compares a value against a bound — that is a threshold"


def test_no_function_here_takes_two_people():
    """A comparative number about a named human is a ranking whatever it is called."""
    for name, fn in vars(facets).items():
        if name.startswith("_") or not inspect.isfunction(fn):
            continue
        params = list(inspect.signature(fn).parameters)
        assert len(params) == 1, f"{name}{tuple(params)} — a facet is about ONE person"


def test_no_identifier_is_named_score_or_rank():
    for node in ast.walk(ast.parse(SRC)):
        names = []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names = [node.id]
        for n in names:
            low = n.lower()
            assert "score" not in low and "rank" not in low


def test_the_module_imports_nothing_that_could_order_people():
    tree = ast.parse(SRC)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").lstrip("."))
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    assert "admission" not in imported, "facets must not reach the ordering function"
    assert not (imported & {"crackscore", "metrics", "rank", "heapq", "operator"})


# --- the arithmetic, on the rows the ruling was argued on -------------------

def test_breadth_and_depth_are_recorded_separately_and_never_combined():
    """simonw 54 repos at 5.72 pushes/repo, t3dotgg 2 repos at 45.0. Averaging or
    multiplying those puts t3dotgg next to a fork farm on one number."""
    s = window_facets(SIMONW)
    t = window_facets(T3)
    assert s["distinct_repos"] == 54 and round(s["pushes_per_repo"], 2) == 5.72
    assert t["distinct_repos"] == 2 and t["pushes_per_repo"] == 45.0
    assert set(s) == set(FACET_NAMES), "no combined axis is emitted"


def test_the_f019_triple_is_emitted_whole_or_not_at_all():
    """repos_not_owned alone cannot tell a template bot from a prolific contributor;
    the three terms side by side can. Emitting one without the others publishes the half
    of the evidence that misleads."""
    got = window_facets(SIMONW)
    assert {"repos_not_owned", "not_owned_basenames", "not_owned_owners"} <= set(got)
    diego = WindowMetrics(window_days=90, pushes=2275, distinct_repos=130, active_days=87,
                          repos_not_owned=124, not_owned_basenames=2, not_owned_owners=124)
    d = window_facets(diego)
    assert (d["repos_not_owned"], d["not_owned_owners"], d["not_owned_basenames"]) \
        == (124, 124, 2)


def test_a_zero_activity_row_is_all_zeros_never_a_crash_and_never_a_nan():
    """78 of the real 175-owner pool has zero 90d activity. That is a labelling case."""
    got = window_facets(WindowMetrics(window_days=90))
    assert set(got) == set(FACET_NAMES)
    assert all(v == 0 for v in got.values())


def test_every_facet_is_a_count_or_a_rate_derived_from_counts():
    got = window_facets(SIMONW)
    for k, v in got.items():
        assert isinstance(v, (int, float)), k
        assert v >= 0, k
    assert isinstance(got["distinct_repos"], int)
    assert isinstance(got["pushes_per_repo"], float)


def test_facets_are_keyed_by_window_name_so_the_site_never_reads_by_position():
    got = facets.facets({7: WindowMetrics(window_days=7, pushes=5, distinct_repos=1),
                         30: WindowMetrics(window_days=30),
                         90: SIMONW})
    assert set(got) == {"7d", "30d", "90d"}
    assert got["90d"]["distinct_repos"] == 54
    assert all(set(v) == set(FACET_NAMES) for v in got.values())


def test_the_mishapos_shape_and_a_human_generalist_sit_on_the_same_axis():
    """WHY DEPTH IS A FLAG INPUT IN `admission` AND A DISPLAY FACT HERE, AND A RANKING
    KEY NOWHERE. 194,964 repos at 1.00 push/repo is one extreme of the axis a human
    generalist occupies; the facet records both without judging either."""
    mishapos = WindowMetrics(window_days=90, pushes=195021, distinct_repos=194964,
                             active_days=90)
    m = window_facets(mishapos)
    assert round(m["pushes_per_repo"], 2) == 1.0
    assert m["distinct_repos"] > window_facets(SIMONW)["distinct_repos"]
    # The facet does not say which of the two is a person. That is the flag's job.


# --- the description honours factual framing -------------------------------

def test_the_description_states_activity_and_never_judges_the_person():
    text = describe_breadth_and_depth(SIMONW)
    assert text == ("309 pushes across 54 repositories on 65 active days "
                    "in the last 90 days")
    for banned in ("cracked", "elite", "prolific", "best", "top", "impressive",
                   "better", "expert", "genius", "rockstar"):
        assert banned not in text.lower()


def test_the_description_pluralises_so_a_one_repo_dev_reads_correctly():
    one = WindowMetrics(window_days=7, pushes=1, distinct_repos=1, active_days=1)
    assert describe_breadth_and_depth(one) == \
        "1 push across 1 repository on 1 active day in the last 7 days"


def test_a_zero_activity_person_is_described_as_an_attribution_fact():
    """The Court settled twice that a low count is a fact about the feed's attribution,
    never a fact about a human. The sentence says "attributed", not "did nothing"."""
    text = describe_breadth_and_depth(WindowMetrics(window_days=90))
    assert text == "no pushes attributed in the last 90 days"
    assert "inactive" not in text and "nothing" not in text
