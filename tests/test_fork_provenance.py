"""T10t/T11t — fork provenance as EVIDENCE, and the separator that does not exist.

THE MOST IMPORTANT TEST IN THIS FILE IS AN EQUALITY, NOT A DISTINCTION.
`test_the_hard_pair_is_indistinguishable_on_this_signal` pins that koala73 (cleared:
human) and diegosouzapw (denied: automation) produce IDENTICAL fork evidence. e01 asked
e02 for a REST lane that would separate them; measured live, it does not. Any future
editor who "fixes" that test by making the two differ has re-derived a separator that is
not in the data, and the next thing they will do is wire it to an auto-clear.

Everything else here is fail-closed plumbing: a REST failure, a truncated sample and an
exhausted budget must all leave the flag exactly where it was.

No network. The live measurements the fixtures encode were taken 2026-08-27.
"""
from __future__ import annotations

import ast
from pathlib import Path

from cerebro.gitintel import admission, fork_provenance
from cerebro.gitintel.fork_provenance import (
    ForkBudget,
    ForkEvidence,
    describe,
    evidence,
    sample_repos,
)
from cerebro.gitintel.gharchive import WindowMetrics


class FakeClient:
    def __init__(self, repos, fail=()):
        self.repos = repos
        self.fail = set(fail)
        self.paths: list[str] = []

    def request(self, path, params=None):
        self.paths.append(path)
        full = path[len("/repos/"):]
        if full in self.fail:
            raise RuntimeError("boom")
        return self.repos.get(full)


def _fork(full, source_full):
    o, _, n = full.partition("/")
    s_o, _, s_n = source_full.partition("/")
    return {"full_name": full, "name": n, "fork": True,
            "owner": {"login": o},
            "source": {"full_name": source_full, "name": s_n, "owner": {"login": s_o}},
            "parent": {"full_name": source_full, "name": s_n, "owner": {"login": s_o}}}


def _origin(full, stars=0):
    o, _, n = full.partition("/")
    return {"full_name": full, "name": n, "fork": False, "owner": {"login": o},
            "stargazers_count": stars}


def _m(login, repos, **kw):
    return WindowMetrics(window_days=90, dominant_repos=tuple(repos),
                         dominant_base=repos[0].partition("/")[2].lower() if repos else "",
                         **kw)


# --- THE FALSIFIED PREMISE, pinned permanently ------------------------------

KOALA_SAMPLE = ["AliXAbdullah03/worldmonitor", "Developer1010x/worldmonitor",
                "dharunashokkumar/worldmonitor", "dyrach1o/worldmonitor",
                "emanuele8888/worldmonitor", "koala73/worldmonitor"]
DIEGO_SAMPLE = ["allanvb/OmniRoute", "Arul-/OmniRoute", "backryun/OmniRoute",
                "benzntech/OmniRoute", "blackwell-systems/OmniRoute",
                "diegosouzapw/OmniRoute"]


def _hard_pair_clients():
    koala = FakeClient({r: _fork(r, "koala73/worldmonitor") for r in KOALA_SAMPLE[:-1]}
                       | {"koala73/worldmonitor": _origin("koala73/worldmonitor", 84341)})
    diego = FakeClient({r: _fork(r, "diegosouzapw/OmniRoute") for r in DIEGO_SAMPLE[:-1]}
                       | {"diegosouzapw/OmniRoute": _origin("diegosouzapw/OmniRoute", 56206)})
    return koala, diego


def test_the_hard_pair_is_indistinguishable_on_this_signal():
    """MEASURED LIVE 2026-08-27, both at max_repos=5:

        koala73       checked 5  own_upstream 5  third_party 0  no_upstream 0
        diegosouzapw  checked 5  own_upstream 5  third_party 0  no_upstream 0

    One carries `cleared: human`, the other `denied: automation`. e01 predicted this
    signal would separate them. It does not, and a rule that cleared koala73 on it would
    clear diegosouzapw too. DO NOT "FIX" THIS TEST BY MAKING THEM DIFFER."""
    kc, dc = _hard_pair_clients()
    k = evidence("koala73", _m("koala73", KOALA_SAMPLE), kc, max_repos=5)
    d = evidence("diegosouzapw", _m("diegosouzapw", DIEGO_SAMPLE), dc, max_repos=5)
    assert (k.own_upstream, k.third_party, k.no_upstream, k.unresolved) == (5, 0, 0, 0)
    assert (d.own_upstream, d.third_party, d.no_upstream, d.unresolved) == (5, 0, 0, 0)
    assert (k.checked, k.third_party) == (d.checked, d.third_party)
    assert k.upstreams == ("koala73/worldmonitor",)
    assert d.upstreams == ("diegosouzapw/OmniRoute",)


def test_both_halves_of_the_hard_pair_get_the_same_sub_shape_name():
    """The consequence, stated as code. The sub-shape is a NAME for the reviewer, and it
    is the SAME name for the cleared account and the denied one."""
    kc, dc = _hard_pair_clients()
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=960,
                      active_days=81, dominant_repos=tuple(KOALA_SAMPLE))
    k = evidence("koala73", _m("koala73", KOALA_SAMPLE), kc, max_repos=5)
    d = evidence("diegosouzapw", _m("diegosouzapw", DIEGO_SAMPLE), dc, max_repos=5)
    kn = [f.name for f in admission.name_fork_subshape(admission.flags(m), k)]
    dn = [f.name for f in admission.name_fork_subshape(admission.flags(m), d)]
    assert "fork_farm_own_upstream" in kn
    assert kn == dn, "the sub-shape does not separate a cleared account from a denied one"


# --- the module returns evidence and exposes no verdict ---------------------

def test_the_module_exposes_no_verdict_shaped_name():
    """No function here answers "is this a fork farm". A name like `is_clear` would be a
    verdict with extra steps, and the next edit would wire it to an auto-exclude."""
    tree = ast.parse(Path("cerebro/gitintel/fork_provenance.py").read_text(encoding="utf-8"))
    banned = ("verdict", "exclude", "clear", "_ok", "ok_")
    for node in ast.walk(tree):
        names = []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names = [node.id]
        for n in names:
            low = n.lower()
            assert not any(b in low for b in banned), f"{n} is verdict-shaped"
            assert low != "ok"


def test_no_public_function_returns_a_bare_boolean_judgement():
    """`evidence()` hands back counts and names. A bool would BE the verdict, whatever
    the function was called."""
    kc, _ = _hard_pair_clients()
    m = _m("koala73", KOALA_SAMPLE)
    assert isinstance(evidence("koala73", m, kc), ForkEvidence)
    assert isinstance(fork_provenance.unevidenced(), ForkEvidence)
    assert isinstance(sample_repos("koala73", m), tuple)
    assert isinstance(describe(fork_provenance.unevidenced()), str)
    # `complete` is the one bool, and it is a fact about the SAMPLE, not about the person.
    assert isinstance(ForkEvidence().complete, bool)


# --- one payload, one call --------------------------------------------------

def test_one_rest_call_per_sampled_repo_and_never_two():
    """`fork`, `source.owner.login` and `parent.full_name` are all in the ONE payload."""
    kc, _ = _hard_pair_clients()
    evidence("koala73", _m("koala73", KOALA_SAMPLE), kc, max_repos=5)
    assert len(kc.paths) == 5
    assert len(set(kc.paths)) == 5
    assert all(p.startswith("/repos/") and p.count("/") == 3 for p in kc.paths)


def test_the_sample_prefers_not_owned_repos_because_the_own_copy_says_nothing():
    got = sample_repos("koala73", _m("koala73", KOALA_SAMPLE), max_repos=5)
    assert "koala73/worldmonitor" not in got, "the own copy is the last slot, not the first"
    assert len(got) == 5


def test_the_own_copy_fills_a_remaining_slot_when_there_is_room():
    got = sample_repos("koala73", _m("koala73", ["a/wm", "koala73/wm"]), max_repos=5)
    assert got == ("a/wm", "koala73/wm")


def test_no_archive_sample_is_no_evidence_and_the_flag_stands():
    got = evidence("x", WindowMetrics(window_days=90, distinct_repos=20), FakeClient({}))
    assert got.checked == 0 and got.complete is False


# --- FAIL-CLOSED: uncertainty never clears anybody --------------------------

def test_a_rest_failure_increments_unresolved_and_never_raises():
    cl = FakeClient({r: _fork(r, "koala73/worldmonitor") for r in KOALA_SAMPLE[1:]},
                    fail={KOALA_SAMPLE[0]})
    got = evidence("koala73", _m("koala73", KOALA_SAMPLE), cl, max_repos=5)
    assert got.unresolved == 1
    assert got.complete is False


def test_an_unresolved_call_leaves_the_bare_fork_farm_name_standing():
    """A flag is never renamed to a sub-shape it did not earn."""
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=960, active_days=81)
    partial = ForkEvidence(checked=4, own_upstream=4, unresolved=1, sampled=("a/b",) * 5)
    names = [f.name for f in admission.name_fork_subshape(admission.flags(m), partial)]
    assert "fork_farm" in names
    assert not any(n.startswith("fork_farm_") for n in names)


def test_a_fork_whose_source_the_payload_omits_is_unresolved_not_no_upstream():
    """Calling it `no_upstream` would invent a shape out of a missing field."""
    cl = FakeClient({"a/b": {"full_name": "a/b", "name": "b", "fork": True,
                             "owner": {"login": "a"}}})
    got = evidence("x", _m("x", ["a/b"]), cl, max_repos=1)
    assert got.unresolved == 1 and got.no_upstream == 0 and got.checked == 0


def test_a_none_payload_is_unresolved_not_a_crash():
    got = evidence("x", _m("x", ["a/b"]), FakeClient({"a/b": None}), max_repos=1)
    assert got.unresolved == 1


# --- the shared budget is a hard ceiling ------------------------------------

def test_a_budget_of_three_over_four_candidates_spends_exactly_three():
    """MEASURED LIVE with cap=3 over the hard pair: koala73 checked 3 truncated,
    diegosouzapw checked 0 truncated, budget used 3."""
    bud = ForkBudget(3)
    cands = [(f"u{i}", [f"o{i}/r", f"u{i}/r"]) for i in range(4)]
    cl = FakeClient({f"o{i}/r": _fork(f"o{i}/r", f"u{i}/r") for i in range(4)}
                    | {f"u{i}/r": _origin(f"u{i}/r") for i in range(4)})
    results = [evidence(login, _m(login, repos), cl, max_repos=2, budget=bud)
               for login, repos in cands]
    assert bud.used == 3 == len(cl.paths)
    assert bud.exhausted is True
    assert results[-1].checked == 0 and results[-1].truncated is True


def test_a_candidate_reached_after_exhaustion_keeps_its_bare_flag():
    """A BUDGET RUNNING OUT NEVER CLEARS ANYBODY and never renames a flag."""
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=960, active_days=81)
    none_left = fork_provenance.unevidenced()
    assert none_left.checked == 0 and none_left.truncated is True
    names = [f.name for f in admission.name_fork_subshape(admission.flags(m), none_left)]
    assert names.count("fork_farm") == 1
    assert not any(n in admission.FORK_SUBSHAPES for n in names)


def test_the_budget_stops_mid_candidate_and_says_so():
    bud = ForkBudget(2)
    cl = FakeClient({f"o{i}/r": _fork(f"o{i}/r", "u/r") for i in range(5)})
    got = evidence("u", _m("u", [f"o{i}/r" for i in range(5)]), cl, max_repos=5, budget=bud)
    assert got.checked == 2 and got.truncated is True and got.complete is False
    assert len(cl.paths) == 2


def test_a_zero_budget_spends_nothing():
    bud = ForkBudget(0)
    cl = FakeClient({"o/r": _fork("o/r", "u/r")})
    got = evidence("u", _m("u", ["o/r"]), cl, max_repos=5, budget=bud)
    assert cl.paths == [] and got.checked == 0 and got.truncated is True


def test_a_partial_sample_is_never_complete_enough_to_name_a_sub_shape():
    """A sub-shape is a claim about a named human's whole pattern. Half a sample does
    not support one, and the safe direction is back to the bare flag and a human."""
    partial = ForkEvidence(checked=2, own_upstream=2, truncated=True, sampled=("a/b", "c/d"))
    assert partial.complete is False


# --- the three sub-shapes ---------------------------------------------------

def _flag_names(ev):
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=960, active_days=81)
    return [f.name for f in admission.name_fork_subshape(admission.flags(m), ev)]


def test_all_own_upstream_names_the_own_upstream_sub_shape():
    ev = ForkEvidence(checked=5, own_upstream=5, sampled=("a",) * 5,
                      upstreams=("koala73/worldmonitor",))
    assert "fork_farm_own_upstream" in _flag_names(ev)


def test_any_third_party_names_the_third_party_sub_shape():
    ev = ForkEvidence(checked=5, own_upstream=4, third_party=1, sampled=("a",) * 5)
    assert "fork_farm_third_party" in _flag_names(ev)


def test_none_are_forks_names_the_no_upstream_sub_shape():
    """The template fan-out shape: hundreds of same-named repos that are independent
    creations rather than forks of one upstream."""
    ev = ForkEvidence(checked=5, no_upstream=5, sampled=("a",) * 5)
    assert "fork_farm_no_upstream" in _flag_names(ev)


def test_a_mixed_own_and_not_a_fork_result_falls_back_to_the_bare_flag():
    ev = ForkEvidence(checked=5, own_upstream=3, no_upstream=2, sampled=("a",) * 5)
    names = _flag_names(ev)
    assert "fork_farm" in names and not any(n.startswith("fork_farm_") for n in names)


def test_every_sub_shape_is_a_flag_and_none_of_them_is_a_clearance():
    """ALL THREE ENTER THE REVIEW QUEUE. None is a verdict."""
    from cerebro.gitintel.denylist import Verdicts
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=960, active_days=81)
    for ev in (ForkEvidence(checked=5, own_upstream=5, sampled=("a",) * 5),
               ForkEvidence(checked=5, third_party=5, sampled=("a",) * 5),
               ForkEvidence(checked=5, no_upstream=5, sampled=("a",) * 5)):
        fired = admission.name_fork_subshape(admission.flags(m), ev)
        assert fired, "a sub-shape is a FLAG; it never empties the flag list"
        assert admission.automation_state(m, "somebody", Verdicts()) == "flagged"


def test_automation_state_is_untouched_by_fork_evidence():
    """`excluded` stays reachable only from `verdicts.denied` and `clear` only from
    nothing-firing or a recorded `cleared:` verdict. The signature does not even take
    evidence, which is the strongest form of "untouched"."""
    import inspect
    sig = inspect.signature(admission.automation_state)
    assert list(sig.parameters) == ["m90", "login", "verdicts"]


# --- evidence strings are for a human ---------------------------------------

def test_the_evidence_string_names_the_upstream_repo_not_a_bare_ratio():
    ev = ForkEvidence(checked=5, own_upstream=5, sampled=("a",) * 5,
                      upstreams=("diegosouzapw/OmniRoute",))
    text = describe(ev)
    assert "diegosouzapw/OmniRoute" in text
    assert "5 fork an upstream this account owns" in text


def test_an_unevidenced_candidate_is_described_as_unevidenced_not_as_clean():
    text = describe(fork_provenance.unevidenced())
    assert "NOT gathered" in text and "flag stands" in text


def test_describe_recommends_nothing():
    for ev in (ForkEvidence(checked=5, own_upstream=5, sampled=("a",) * 5),
               ForkEvidence(checked=5, third_party=5, sampled=("a",) * 5),
               fork_provenance.unevidenced(), None):
        text = describe(ev).lower()
        for banned in ("should", "recommend", "safe to", "likely a bot", "exclude"):
            assert banned not in text


def test_the_flag_evidence_string_gains_the_upstream_when_the_sub_shape_is_named():
    ev = ForkEvidence(checked=5, own_upstream=5, sampled=("a",) * 5,
                      upstreams=("koala73/worldmonitor",))
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=960, active_days=81)
    fired = [f for f in admission.name_fork_subshape(admission.flags(m), ev) if f.name.startswith("fork_farm")]
    assert "koala73/worldmonitor" in fired[0].evidence
    assert "basename concentration" in fired[0].evidence, "the original numbers survive"


# --- backwards compatibility with every e01 caller --------------------------

def test_flags_signature_is_byte_identical_to_e01_so_no_override_seam_opened():
    """e01 forbids EVERY default-valued parameter on the admission entry points, because
    the condemned scorer shipped broken for six production runs behind exactly such a
    seam. Fork provenance is applied after `flags()` returns rather than through a
    keyword on it, so the guard survives e02 unweakened."""
    import inspect
    sig = inspect.signature(admission.flags)
    assert list(sig.parameters) == ["m90"]
    for prm in sig.parameters.values():
        assert prm.default is inspect.Parameter.empty
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=960, active_days=81)
    assert [f.name for f in admission.flags(m)] == ["fork_farm"]


def test_naming_renames_and_never_adds_or_removes_a_flag():
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=960, active_days=81)
    base = admission.flags(m)
    ev = ForkEvidence(checked=5, own_upstream=5, sampled=("a",) * 5)
    named = admission.name_fork_subshape(base, ev)
    assert len(named) == len(base)
    assert [f.metric_values for f in named] == [f.metric_values for f in base]
    assert admission.name_fork_subshape(base, None) == base


def test_naming_leaves_a_non_fork_flag_untouched():
    """A high_push_rate flag beside a fork_farm one must come back unchanged."""
    m = WindowMetrics(window_days=90, distinct_repos=24, max_basename_group=24,
                      repos_not_owned=23, not_owned_basenames=1, pushes=4000, active_days=81)
    base = admission.flags(m)
    assert {f.name for f in base} == {"high_push_rate", "fork_farm"}
    named = admission.name_fork_subshape(
        base, ForkEvidence(checked=5, third_party=5, sampled=("a",) * 5))
    assert {f.name for f in named} == {"high_push_rate", "fork_farm_third_party"}
