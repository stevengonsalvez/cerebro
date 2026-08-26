"""T10 — fork provenance: the REST lane e01 asked for, and the answer it did not want.

WHAT e01 ASKED FOR. `config/devs_denylist.yaml`'s header records the gap in prose: the
`fork_farm` shape fires identically on a fork farm and on a maintainer working across
forks of their OWN project, and e01 had no REST lane to tell them apart. It named the
separator it expected: "whether the not-owned repos are forks of an upstream the person
also authors".

THAT SEPARATOR DOES NOT EXIST. Measured against the live API while planning this epic:

    koala73        cleared: human      koala73/worldmonitor    fork: false   84,332 stars
                                       michaeldubu/worldmonitor -> source koala73/worldmonitor
    diegosouzapw   denied: automation  diegosouzapw/OmniRoute  fork: false   56,193 stars
                                       Chewji9875/OmniRoute     -> source diegosouzapw/OmniRoute

Both accounts author the upstream. Both push into other people's forks of it. They are
INDISTINGUISHABLE on this signal, and one carries a `cleared:` verdict while the other
carries `denied:`. A rule that clears koala73 on fork provenance clears diegosouzapw too.
A test pins the equality permanently so no future editor re-derives a separator that is
not there.

SO THIS MODULE RETURNS EVIDENCE AND NEVER A VERDICT. There is no function here that
answers "is this a fork farm". There is no boolean judgement, no `clear`, no `exclude`,
no `ok` — a test asserts the module exposes no verdict-shaped name at all. What it
produces is the upstream repo names, so the human reviewer reads
`forks of diegosouzapw/OmniRoute (not a fork itself)` instead of a bare concentration
ratio, and makes the same decision far more cheaply. The Court settled this shape of
problem twice (Q1, Q7): the boundary is continuous and safety rests on shape evidence
plus a human loop, never on one more clever predicate.

FAIL-CLOSED, ALWAYS. A REST failure increments `unresolved`. An exhausted budget returns
`checked=0, truncated=True`. Neither clears anybody and neither renames a flag to a
sub-shape it did not earn. Uncertainty is not a clearance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: The only path this module calls. `fork`, `source.owner.login` and `parent.full_name`
#: all arrive in this ONE payload, so provenance for a repo costs exactly one call and
#: never two. Public read; on the F053 allowlist.
REPO_PATH = "/repos/{owner}/{repo}"

#: Repos sampled per flagged candidate. Bounds ONE candidate, and nothing bounds the
#: number of flagged candidates — which is why `ForkBudget` exists beside it.
DEFAULT_MAX_REPOS = 5

#: The run-wide ceiling on fork-provenance REST calls. 300 was an ASSUMPTION (5 sampled
#: repos x an assumed <= 60 flagged candidates; e01 flagged ~24 of 167). Nothing in the
#: design caps the flag RATE and fan-out grows the pool, so an expanded pool could blow
#: the assumption silently. It is a knob now, not an estimate.
DEFAULT_FORK_BUDGET = 300


class ForkBudget:
    """A hard, shared, decrementing ceiling on this run's fork-provenance calls.

    Shared across every flagged candidate rather than held per candidate: a per-candidate
    bound multiplied by an uncapped candidate count is not a bound at all. When it hits
    zero the lane stops mid-candidate and says so; it does not borrow, and it never
    silently continues.
    """

    def __init__(self, cap: int = DEFAULT_FORK_BUDGET):
        self.cap = max(0, int(cap))
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def take(self) -> bool:
        """Claim one call. False when there is nothing left to claim."""
        if self.exhausted:
            return False
        self.used += 1
        return True


@dataclass(frozen=True)
class ForkEvidence:
    """What the sampled repos turned out to be. Counts and names. No judgement.

    `checked` is repos actually FETCHED, so `checked == 0` with `truncated` set is the
    honest shape of "the budget ran out before we got here" — distinct from "we looked
    and found nothing", which is `checked > 0` with three zeros.
    """

    checked: int = 0
    #: The sample forks a repo the candidate themselves owns.
    own_upstream: int = 0
    #: The sample forks somebody else's repo.
    third_party: int = 0
    #: The sample is not a fork at all — the template fan-out shape, where hundreds of
    #: same-named repos are independent creations rather than forks of one upstream.
    no_upstream: int = 0
    #: The distinct upstream `owner/repo` names found. This is the payload the reviewer
    #: actually reads.
    upstreams: tuple[str, ...] = ()
    #: The repos this evidence was gathered from, so the reviewer can check the sample.
    sampled: tuple[str, ...] = ()
    #: The sample or the run budget cut the look short — the evidence is PARTIAL.
    truncated: bool = False
    #: A REST call failed. FAIL-CLOSED: the flag stands, unchanged.
    unresolved: int = 0

    @property
    def complete(self) -> bool:
        """Enough was resolved to name a sub-shape at all.

        Deliberately strict: partial evidence and unresolved calls both disqualify. A
        sub-shape name is a claim about a named human's whole pattern, and half a sample
        does not support one.
        """
        return self.checked > 0 and not self.truncated and self.unresolved == 0

    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = asdict(self)
        d["upstreams"] = list(self.upstreams)
        d["sampled"] = list(self.sampled)
        return d


def sample_repos(login: str, m90, max_repos: int = DEFAULT_MAX_REPOS) -> tuple[str, ...]:
    """Up to `max_repos` from the dominant basename group, NOT-OWNED ones first.

    The candidate's own copy of the repo tells you nothing — of course they own it. The
    question is what the OTHER copies are, so the not-owned entries are sampled first and
    the candidate's own repo only fills a remaining slot (where it is still useful: it is
    how `own_upstream` gets its name to compare against).
    """
    repos = tuple(getattr(m90, "dominant_repos", ()) or ())
    if not repos:
        return ()
    low = (login or "").strip().lower()
    not_owned = [r for r in repos if _owner(r).lower() != low]
    owned = [r for r in repos if _owner(r).lower() == low]
    ordered = sorted(not_owned, key=str.lower) + sorted(owned, key=str.lower)
    return tuple(ordered[:max(0, int(max_repos))])


def evidence(login: str, m90, client, *, max_repos: int = DEFAULT_MAX_REPOS, budget=None):
    """Resolve up to `max_repos` of the candidate's dominant-basename repos to upstreams.

    ONE `GET /repos/{owner}/{repo}` per sampled repo. `fork`, `source.owner.login` and
    `parent.full_name` are all in that payload, so there is never a second call, and the
    client's 24h cache makes a same-day re-run free.

    `budget`, when given, is the run-wide `ForkBudget`. It is decremented per call and
    the loop STOPS mid-candidate when it hits zero, returning what it has with
    `truncated=True`. Partial evidence is honest evidence; a lane that quietly kept going
    past its ceiling would surface as a 403 an hour later.

    NEVER RAISES. Any exception increments `unresolved` and the caller's flag stands.
    """
    sampled = sample_repos(login, m90, max_repos)
    if not sampled:
        # No archive sample at all -> no evidence. FAIL-CLOSED: the flag stands.
        return ForkEvidence(sampled=(), truncated=bool(getattr(m90, "distinct_repos", 0)))

    checked = 0
    own = third = none_ = 0
    unresolved = 0
    upstreams: list[str] = []
    used: list[str] = []
    truncated = False
    low = (login or "").strip().lower()

    for full in sampled:
        if budget is not None and not budget.take():
            truncated = True
            break
        used.append(full)
        owner, _, name = full.partition("/")
        try:
            data = client.request(REPO_PATH.format(owner=owner, repo=name))
        except Exception as exc:  # noqa: BLE001 — fail-closed, never fatal
            log.warning("fork_provenance: %s failed: %s", full, exc)
            unresolved += 1
            continue
        if not isinstance(data, dict):
            unresolved += 1
            continue
        checked += 1
        upstream = _upstream(data)
        if not data.get("fork"):
            none_ += 1
            continue
        if not upstream:
            # A fork whose source the payload did not carry is UNRESOLVED, not a
            # `no_upstream`: calling it one would invent a shape from a missing field.
            unresolved += 1
            checked -= 1
            continue
        upstreams.append(upstream)
        if _owner(upstream).lower() == low:
            own += 1
        else:
            third += 1

    if len(used) < len(sampled):
        truncated = True

    return ForkEvidence(
        checked=checked,
        own_upstream=own,
        third_party=third,
        no_upstream=none_,
        upstreams=tuple(sorted(set(upstreams), key=str.lower)),
        sampled=tuple(used),
        truncated=truncated,
        unresolved=unresolved,
    )


def unevidenced() -> ForkEvidence:
    """What a candidate the budget never reached gets.

    `checked=0, truncated=True`. Their `fork_farm` flag STANDS unchanged and their
    sub-shape is not named. A budget running out never clears anybody.
    """
    return ForkEvidence(checked=0, truncated=True)


def describe(ev) -> str:
    """A one-line evidence string for the review queue and the verdict block.

    This is the whole point of the lane: the reviewer sees the upstream repo names
    instead of a bare ratio. It states what was found and stops — it recommends nothing.
    """
    if ev is None:
        return "no fork provenance gathered"
    if ev.checked == 0:
        return ("fork provenance NOT gathered (budget exhausted or no archive sample) — "
                "the flag stands unevidenced")
    parts = [f"{ev.checked} of {len(ev.sampled)} sampled repos resolved"]
    if ev.own_upstream:
        parts.append(f"{ev.own_upstream} fork an upstream this account owns")
    if ev.third_party:
        parts.append(f"{ev.third_party} fork somebody else's repo")
    if ev.no_upstream:
        parts.append(f"{ev.no_upstream} are not forks at all")
    if ev.unresolved:
        parts.append(f"{ev.unresolved} unresolved (flag stands)")
    if ev.upstreams:
        parts.append("upstreams: " + ", ".join(ev.upstreams))
    if ev.truncated:
        parts.append("PARTIAL sample")
    return "; ".join(parts)


def _owner(full_name: str) -> str:
    return (full_name or "").partition("/")[0]


def _upstream(data: dict) -> str:
    """`source.full_name` if present, else `parent.full_name`, else ''.

    `source` is the root of the fork chain and `parent` the immediate one; for a
    single-level fork they are the same repo. Preferring `source` answers "whose project
    is this ultimately", which is the question the reviewer is asking.
    """
    for key in ("source", "parent"):
        node = data.get(key)
        if isinstance(node, dict):
            full = str(node.get("full_name") or "").strip()
            if full:
                return full
            owner = node.get("owner")
            name = str(node.get("name") or "").strip()
            if isinstance(owner, dict) and owner.get("login") and name:
                return f"{owner['login']}/{name}"
    return ""
