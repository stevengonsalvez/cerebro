"""F008/F015 — three lanes in, one profile per person out.

WITHOUT THIS MODULE DAY ONE PUBLISHES TWO PAGES ABOUT ONE NAMED HUMAN. The vault lane
finds `simonw` because notes cite `simonw/llm`; the fan-out lane finds `SimonW` again on
`datasette/datasette`; the roster lane seeds him a third time from `cracked_devs.yaml`.
They are one person and the pool has to say so before anything downstream renders him.

TWO THINGS LIVE HERE AND NEITHER IS A SCORE.

1. `roster_lane()` — F008's always-profiled seeds, and the SKIP LIST that makes "never
   suppressed" auditable rather than promised.
2. `assemble()` — slug-keyed identity dedup with a provenance UNION, order-independent
   by construction.

WHY THE MERGE IS ORDER-INDEPENDENT AND WHY THAT IS TESTED BY PERMUTATION. Lane order is
an accident of how the run was invoked (`--lanes fanout,vault` is as legal as
`vault,fanout`). If merge results depended on it, the same corpus would publish different
provenance on different days and the transparency page would be quietly wrong about a
named person. Every merge rule below is therefore a set operation or a fixed precedence,
never "first writer wins": `signal_hashes` and `via_repos` are unions, `discovered_via`
is a declared precedence, `name` is first-non-empty by that same precedence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: `discovered_via`'s vocabulary, widened from e01's bare "vault", and the precedence
#: the single-string field resolves by. A person the vault cites DIRECTLY is
#: vault-discovered even when fan-out also surfaced them: the strongest provenance claim
#: the pool can make about somebody is the one the profile copy has to stand behind.
#: `discovered_via_all` keeps the full set, so widening the vocabulary loses nothing.
LANE_PRECEDENCE = ("vault", "roster", "fanout")

#: The reason string for a roster dev with no `github:` handle. Machine-readable on
#: purpose: the lane census prints it, so a reader sees all seven roster names and why
#: three produced no pool entry, instead of grepping stdout for a log line.
NO_HANDLE = "no github handle"


@dataclass(frozen=True)
class Cand:
    """One person in the pool, after every lane that found them has been merged.

    NO VOLUME FIELDS, in this dataclass or anywhere reachable from it. There is no
    contribution count, no follower count, no star count and no score — the fan-out lane
    drops the first at its own boundary and the rest never enter the devs lane at all.
    """

    login: str
    signal_hashes: tuple[str, ...] = ()
    via_repos: tuple[str, ...] = ()
    #: One of LANE_PRECEDENCE. The single string e04 renders.
    discovered_via: str = ""
    #: The curated display name. The roster lane is where the frozen `name` field stops
    #: being None — no other lane knows what a person is called.
    name: str = ""
    #: Every lane that produced this person, sorted. Additive: e04 renders it in the
    #: provenance section and it makes the single-string field's precedence auditable.
    discovered_via_all: tuple[str, ...] = ()


@dataclass(frozen=True)
class Skip:
    """A roster dev the login-keyed pool structurally cannot carry, and why.

    This is a RECORD, not a log line. F008's Court verdict is "always profiled", which is
    a statement about suppression; a dev with no GitHub handle is not suppressed, they
    are unrepresentable in a login-keyed pool, and the difference is only legible if the
    run emits the name and the reason as data a census can print.
    """

    name: str
    reason: str


def slug(login: str) -> str:
    """The identity key: lowercased, `@`-stripped, whitespace-stripped login.

    The same rule as `CrackedDev.slug`, restated here for LOGINS rather than re-used from
    the dataclass, so the pool does not take a dependency on the roster type. A pool that
    imported `CrackedDev` to key itself would break the moment a lane produced a login
    that never came from the roster, which is every lane but one.
    """
    return (login or "").strip().lstrip("@").lower()


def roster_lane(path=None):
    """F008 — the curated roster as pool candidates. Returns `(entries, skipped)`.

    THE ARITHMETIC, BECAUSE IT IS NOT WHAT THE FEATURE ROW SAYS. `cracked_devs.yaml`
    carries SEVEN devs and only FOUR have a `github:` handle (bcherny, t3dotgg,
    mattpocock, simonw). Pieter Levels, Skirano and Sentient Agency are `github: null`.
    The devs pool is login-keyed, so this lane emits four entries and records three
    skips. Anything asserting seven is asserting against data that does not exist.

    A HANDLE IS NEVER INVENTED. Not from the `x:` handle, not from the display name, not
    from anything. Guessing would attach a published profile to an account no human
    confirmed belongs to that person — the failure the verification doctrine names as
    strictly worse than no page. Populating the field is an owner edit to the YAML, and
    when it happens this lane emits more entries with zero code change.

    Roster devs carry NO signal hashes from this lane. The dedup union supplies real
    provenance for whichever of the four the vault lane also found; one the vault lane
    never produced therefore FAILS the provenance floor, and that is recorded rather than
    excused. "Always profiled" is a rule about suppression, not a licence to publish a
    page with no answer to "why is this person here".
    """
    from .roster import load_roster

    devs, _wiring = load_roster(path)
    entries: list[Cand] = []
    skipped: list[Skip] = []
    for dev in devs:
        handle = slug(dev.github)
        if not handle:
            skipped.append(Skip(name=dev.name, reason=NO_HANDLE))
            continue
        entries.append(Cand(
            login=dev.github.strip().lstrip("@"),
            signal_hashes=(),
            via_repos=(),
            discovered_via="roster",
            name=dev.name,
            discovered_via_all=("roster",),
        ))
    entries.sort(key=lambda c: slug(c.login))
    skipped.sort(key=lambda s: s.name)
    return entries, skipped


def assemble(*lanes):
    """F015 — one person, one entry, whatever order the lanes ran in.

    Every rule is a set operation or a fixed precedence, so all permutations of the input
    lanes produce a byte-identical result:

      signal_hashes      UNION, sorted
      via_repos          UNION, sorted (case-insensitively, then stably)
      name               first non-empty by LANE_PRECEDENCE
      discovered_via     single string, by LANE_PRECEDENCE
      discovered_via_all every lane that produced them, sorted

    The surviving `login` is the one from the highest-precedence lane, which is what
    keeps display casing stable: the roster's curated `simonw` wins over a fan-out
    payload's `SimonW`, and neither changes the key.

    Output is sorted by key. Candidates with an empty slug are dropped: a blank login is
    not a person and cannot be keyed.
    """
    acc: dict[str, dict] = {}
    for lane in lanes:
        for cand in lane or ():
            key = slug(cand.login)
            if not key:
                continue
            entry = acc.get(key)
            if entry is None:
                entry = acc[key] = {
                    "logins": {}, "hashes": set(), "repos": set(),
                    "names": {}, "lanes": set(),
                }
            via = (cand.discovered_via or "").strip().lower()
            for lane_name in set(cand.discovered_via_all or ()) | ({via} if via else set()):
                entry["lanes"].add(lane_name)
            entry["hashes"].update(cand.signal_hashes or ())
            entry["repos"].update(cand.via_repos or ())
            if via:
                entry["logins"].setdefault(via, cand.login)
                if (cand.name or "").strip():
                    entry["names"].setdefault(via, cand.name.strip())

    out: list[Cand] = []
    for key, e in sorted(acc.items()):
        lanes_present = e["lanes"]
        via = _by_precedence(lanes_present) or ""
        login = _first_by_precedence(e["logins"]) or key
        name = _first_by_precedence(e["names"]) or ""
        out.append(Cand(
            login=login,
            signal_hashes=tuple(sorted(e["hashes"])),
            via_repos=tuple(sorted(e["repos"], key=lambda r: (r.lower(), r))),
            discovered_via=via,
            name=name,
            discovered_via_all=tuple(sorted(lanes_present)),
        ))
    return out


def _by_precedence(names):
    for lane in LANE_PRECEDENCE:
        if lane in names:
            return lane
    return next(iter(sorted(names)), None)


def _first_by_precedence(by_lane: dict):
    """The value from the highest-precedence lane that supplied one.

    Falls back to a sorted scan so a lane name outside LANE_PRECEDENCE still resolves
    deterministically rather than by dict insertion order, which would reintroduce the
    lane-order dependence this whole module exists to remove.
    """
    for lane in LANE_PRECEDENCE:
        if by_lane.get(lane):
            return by_lane[lane]
    for lane in sorted(by_lane):
        if by_lane[lane]:
            return by_lane[lane]
    return None


# --- F053/F056: the budget, and the ONE paid step ---------------------------

#: The activity floor the free lane already answers, restated here as the gate in front
#: of the only paid step. Same constant and same meaning as `admission.MIN_ACTIVE_DAYS_90D`
#: — imported rather than re-declared so the two can never drift apart.
def _min_active_days() -> int:
    from .admission import MIN_ACTIVE_DAYS_90D
    return MIN_ACTIVE_DAYS_90D


#: What `paid_prefilter` records on a candidate it never spent a call on. NOT a verdict
#: and NOT a suppression: a deferred API call is not a dropped person, and the Court
#: settled twice (Q7, Q8) that a low activity count is an attribution fact, never a fact
#: about a human. The marker exists so a downstream writer can tell "checked and human"
#: apart from "not checked", which `admitted: true` alone cannot express.
PREFILTER_VERIFIED = "rest_verified"
PREFILTER_DEFERRED = "deferred_below_activity_floor"
PREFILTER_TRUNCATED = "deferred_rest_budget"

#: The fourth marker, and the one `paid_prefilter` never writes. A candidate that never
#: entered the paid path at all is NOT "checked and human", and the three markers above
#: cannot say so: two of them mean "we deferred a call we intended to make", and
#: `rest_verified` is a claim that a `GET /users/{login}` came back a person.
#:
#: A ROSTER-ONLY DEV IS THE CASE. `config/cracked_devs.yaml` is a hand-written list; being
#: on it is a curation fact, not an API result. Defaulting those to `rest_verified` would
#: put a verification claim in the record for an account nobody ever called, which is the
#: exact confusion the marker was introduced to prevent — the schema note binds e04 to
#: "must NOT render an unchecked account as a verified one", and this is what e04 renders
#: instead. It is never an admission signal and never a suppression: roster devs are
#: profiled with the low-n label like everyone else.
PREFILTER_ROSTER = "curated_roster"

#: The whole vocabulary, so a consumer can validate a record without re-listing it.
PREFILTER_STATES = (PREFILTER_VERIFIED, PREFILTER_DEFERRED, PREFILTER_TRUNCATED,
                    PREFILTER_ROSTER)

#: The two markers that mean A CALL WAS INTENDED AND NOT MADE, which is the condition the
#: F066 gate exists to catch. `curated_roster` is deliberately NOT in here: no call was
#: intended, because a human wrote the login into `config/cracked_devs.yaml` by hand. The
#: distinction matters at the gate — a deferral is fixable by raising `--rest-budget`,
#: and a curated entry is not fixable by anything, so failing on it would be an
#: unclearable stop on the owner's own list.
PREFILTER_UNCHECKED = (PREFILTER_DEFERRED, PREFILTER_TRUNCATED)


@dataclass
class Budget:
    """Every cost this run incurred, actual against cap, written into the artifact.

    ONE ACCOUNTANT. `rest_calls_used` and `rest_cache_hits` are DELTAS off the client's
    own counters and off nothing else, so no lane can keep a private tally that
    disagrees with what actually left the process. A budget re-derived by counting call
    sites is a second accountant and the two disagree the first time somebody adds a
    retry.

    A ZERO `rest_calls_used` ON A COLD RUN IS A FAILED VALIDATION, NOT A CHEAP RUN. It
    means the client counter is unwired and every other number here is unmeasured — the
    exact condition that let this repo print "0 REST calls" for six months.

    TRUNCATION IS NAMED OR IT IS A DEFECT. Both `truncated` and `fork_budget_exhausted`
    carry a count beside them, because a budget that silently stops doing work reports a
    clean run and surfaces an hour later as a 403.
    """

    rest_calls_used: int = 0
    rest_cache_hits: int = 0
    rest_calls_cap: int = 0
    clickhouse_scans: int = 0
    #: The paid pre-filter hit `rest_calls_cap` and stopped. `skipped_logins` counts who.
    truncated: bool = False
    skipped_logins: int = 0
    #: The fork-provenance lane's own hard ceiling, separate because it is a separate
    #: knob: nothing in the design caps the FLAG RATE, so an expanded pool can flag more
    #: candidates than any per-candidate bound anticipated.
    fork_calls_used: int = 0
    fork_calls_cap: int = 0
    fork_budget_exhausted: bool = False
    #: Flagged candidates left with `checked == 0` when the fork budget ran out. Their
    #: flags STAND. A budget running out never clears anybody.
    fork_unevidenced: int = 0
    #: Candidates the free activity floor deferred, so no REST call was ever spent on
    #: them. Recorded, never suppressed.
    prefilter_deferred: int = 0
    #: Fan-out candidates the paid pre-filter checked and rejected as non-human.
    prefilter_rejected: int = 0

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


@dataclass
class PrefilterResult:
    kept: list = field(default_factory=list)
    deferred: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    calls_used: int = 0
    truncated: bool = False


def paid_prefilter(candidates, metrics, client, *, cap, order=None):
    """F011's humanness check on fan-out candidates, ordered CHEAPEST-FIRST.

    THE ARITHMETIC THAT DICTATES THE ORDERING. Calling `get_user` on every contributor
    is 60 repos x up to 100 contributors ~ 6,000 cold REST calls: 1.2 hours of the whole
    hourly budget, spent on people the free ClickHouse lane has already shown have no
    activity at all. So the pipeline runs:

        contributors page -> inline `type != User` reject   (FREE, at the lane boundary)
        dedup against the existing pool                     (FREE)
        ClickHouse pool scan, one IN list                   (FREE, 3 queries per run)
        activity floor, >= 5 active days / 90d              (FREE, off that scan)
        get_user                                            <- the ONLY paid step

    A CANDIDATE BELOW THE FLOOR IS DEFERRED, NOT DROPPED. They come back in `deferred`
    carrying `PREFILTER_DEFERRED`, they enter the pool, and they simply never cost a call.
    Suppression stays forbidden; deferring an API call is not suppression. What the
    marker buys is honesty downstream: `admitted: true` cannot express "nobody checked",
    and a writer that cannot tell the two apart would publish an unverified account with
    the same confidence as a verified one.

    `cap` is a HARD ceiling on calls this step may spend. On exhaustion the remainder come
    back in `deferred` carrying `PREFILTER_TRUNCATED` and `truncated=True` — recorded
    truncation is a budget, silent truncation is a defect.

    `order` is the F063 work order (recurrence-first). It orders WORK. It is never read
    as a fact about a person and never enters a record.
    """
    from .owner_resolve import is_human

    floor = _min_active_days()
    ranked = list(candidates)
    if order is not None:
        # A WORK INDEX, not a ranking. It records the position of each login in the
        # F063 recurrence-ordered work queue so the paid calls are spent where the
        # corpus keeps pointing; it is never read as a fact about a person and never
        # reaches a record. Named `work_index` rather than `rank` because
        # `tests/test_no_composite.py` forbids the identifier outright, and that guard
        # is worth more than the shorter name.
        work_index = {slug(k): i for i, k in enumerate(order)}
        ranked.sort(key=lambda c: (work_index.get(slug(c.login), len(work_index)),
                                   slug(c.login)))
    else:
        ranked.sort(key=lambda c: slug(c.login))

    out = PrefilterResult()
    spent = 0
    for cand in ranked:
        m = (metrics.get(cand.login) or metrics.get(slug(cand.login)) or {})
        m90 = m.get(90)
        active = getattr(m90, "active_days", 0)
        if active < floor:
            out.deferred.append((cand, PREFILTER_DEFERRED))
            continue
        if spent >= cap:
            out.truncated = True
            out.deferred.append((cand, PREFILTER_TRUNCATED))
            continue
        spent += 1
        try:
            user = client.get_user(cand.login)
        except Exception:  # noqa: BLE001 — one bad account must not sink the lane
            user = None
        if user and is_human(user):
            out.kept.append(cand)
        else:
            # F011's ruling, e01's calibration, not this epic's to re-open. An account
            # the humanness check rejects is not a person being suppressed.
            out.rejected.append(cand)

    out.calls_used = spent
    out.kept.sort(key=lambda c: slug(c.login))
    out.deferred.sort(key=lambda pair: slug(pair[0].login))
    out.rejected.sort(key=lambda c: slug(c.login))
    return out
