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
