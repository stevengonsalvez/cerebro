"""F003/F063/F053 — the contributor fan-out lane, one hop off the vault's own repos.

THE SECOND DISCOVERY LANE. e01 could only ever see people the vault cites BY NAME. This
lane asks the repos the vault already cited who else builds them, which is how a pool
anchored in the corpus reaches engineers the corpus has not written about yet. The hop
is exactly ONE and the record says so: a fan-out candidate is here because of a repo,
never because a signal note named the person.

WHY REST AND NOT THE ARCHIVE (Court settled Q3, on measurement, not preference).
The GH-Archive co-pusher alternative (F004) sees only the literal git-push actor, so on
any repo that merges through PRs it returns bots or a lone maintainer: HeyPuter/puter
returned 6 co-pushers against 400 REST contributors (1.5% recall), n8n-io/n8n 96 against
425 (22.6%), and `copyberry[bot]` came back #2 on openai/codex. REST returns correctly
attributed all-time authorship for one call per repo.

THE PAGE-1 CAP IS A WORK CAP AND IS DISCLOSED, NOT HIDDEN. GitHub returns the
contributors page in COMMIT-COUNT ORDER (measured on simonw/llm: 1170, 10, 5, 5, 4...),
so reading page 1 only is volume-biased by construction. That is admissible as the F063
category the Court ratified — ORDERING OF WORK, NEVER A SCORE INPUT — and three
properties stop the bias leaking downstream:

  1. `contributions` is DROPPED AT THE BOUNDARY. It enters no dataclass, no record, no
     artifact and no fixture. `FanoutCandidate` has no field for it and none for
     followers or stars either, and a test asserts the field set by AST.
  2. The lane returns logins SORTED BY LOGIN. GitHub's ordering is destroyed here, before
     any downstream consumer can see it.
  3. Every fan-out candidate then meets the SAME floors as a vault-lane candidate. There
     is no fan-out fast path and no fan-out privilege.

Walking every page was rejected on cost shape rather than principle: 400 contributors is
4 calls, and the tail of a commit-count-ordered list is one-commit drive-bys — the
lowest-value candidates at the highest marginal cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .owner_resolve import VENDOR_ORGS

log = logging.getLogger(__name__)

#: The only path this module calls. Page 1, `per_page=100`, one REST call per repo.
CONTRIBUTORS_PATH = "/repos/{full_name}/contributors"

#: F053, the asserted public-read boundary. Every REST path the DEVS LANE may call,
#: as templates. `tests/test_public_boundary.py` sweeps the lane's modules and requires
#: every API-shaped string literal to match one of these — the boundary is a property of
#: the code, checked on every build, precisely because e02 is the epic that adds a lane
#: and the xyora token carries far more scope than anything here needs.
PUBLIC_READ_PATHS = (
    "/users/{login}",
    "/repos/{owner}/{repo}",
    "/repos/{owner}/{repo}/contributors",
)

#: One page. Not a quality signal, not a ranking, not a sample size chosen for
#: statistical reasons — a bound on work, disclosed in the artifact.
PER_PAGE = 100


@dataclass(frozen=True)
class FanoutCandidate:
    """One person a vault repo surfaced, and the provenance of that hop.

    NO `contributions` FIELD. NO `followers`. NO `stars`. NO `stargazers_count`. The
    absence is the mechanism, not an oversight: GitHub hands this lane a commit count on
    every contributor and the only safe place to drop it is here, at the boundary, where
    a field that does not exist cannot be read by anything downstream. Asserted by
    `tests/test_no_composite.py` over the dataclass's field set.
    """

    login: str
    #: The seed repos that surfaced them. `provenance_repos` on the record.
    via_repos: tuple[str, ...] = ()
    #: Inherited through exactly ONE hop from those repos' signal notes. A fan-out
    #: candidate's provenance is "a repo the vault cited", never "the vault cited you".
    signal_hashes: tuple[str, ...] = ()


def contributors(full_name: str, client) -> tuple[str, ...]:
    """Page 1 of `/repos/{full}/contributors` -> human logins, SORTED ALPHABETICALLY.

    ONE REST CALL. The bot/org rejects happen inline off the payload's own `type` field
    at zero extra cost — `github-actions[bot]` comes back as `type: "Bot"`, so the
    expensive `get_user` pre-filter never has to see it (§3.3's free-first ordering).

    A 404, a 403, an empty repo or a malformed payload returns `()` and logs. One dead
    seed repo must not sink the lane; that is the `_resolve_owners` precedent from e01.

    The return is sorted so the API's commit-count ordering cannot survive the call.
    """
    path = CONTRIBUTORS_PATH.format(full_name=full_name)
    try:
        data = client.request(path, {"per_page": PER_PAGE})
    except Exception as exc:  # noqa: BLE001 — one dead repo must not sink the lane
        log.warning("fanout: contributors failed for %s: %s", full_name, exc)
        return ()
    if not isinstance(data, list):
        return ()

    out: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        login = str(row.get("login") or "").strip()
        if not login or not _admissible(login, row.get("type")):
            continue
        out.add(login)
    # Sorted, not "sorted for tidiness": this is where the volume ordering dies.
    return tuple(sorted(out, key=str.lower))


def _admissible(login: str, type_: object) -> bool:
    """The three FREE rejects available straight off the contributors payload.

    Nothing here is a quality judgement and nothing here is a shape flag. It is the
    same F011 humanness pre-filter e01 already applies, moved earlier so the paid
    `get_user` call is never spent on an account the payload itself already disqualified.
    Real automation with a human-looking name is caught downstream by SHAPE, per the
    Court's ruling that name-pattern filtering is provably insufficient.
    """
    if str(type_ or "").lower() != "user":
        return False
    low = login.lower()
    if low.endswith("[bot]"):
        return False
    return low not in VENDOR_ORGS


def work_queue(seeds, limit: int):
    """F063: seed REPOS ordered by signal recurrence, truncated to `limit`.

    ORDERING OF WORK, NEVER A SCORE INPUT, and the distinction is structural rather than
    a promise: this function orders REPOSITORIES, it never touches a person, and the
    recurrence count it sorts on is not returned and enters no record field. A test
    asserts the count is absent from every artifact field.

    The corpus's recurrers go first (`claude-code` 36 notes, `codex` 8, `llm` 4), so a
    truncated run spends its calls on the repos the vault keeps coming back to rather
    than on whichever repo happened to sort first alphabetically. Ties break on the
    lowercased key so the queue is byte-stable run to run.
    """
    ordered = sorted(seeds, key=lambda s: (-len(s.signal_hashes), s.key))
    n = max(0, int(limit))
    return ordered[:n]


def fanout_lane(seeds, client, *, limit: int, log=None):
    """Run the whole lane: `work_queue` -> `contributors` per repo -> merged candidates.

    Returns `(candidates, repos_read)`. `candidates` is keyed on the login and carries
    the UNION of every seed repo that surfaced the person and of those repos' signal
    hashes, so somebody who contributes to three vault-cited repos arrives once with all
    three, not three times.
    """
    emit = log or (lambda *_a: None)
    work = work_queue(seeds, limit)
    acc: dict[str, dict] = {}
    for i, repo in enumerate(work, 1):
        found = contributors(repo.full_name, client)
        for login in found:
            entry = acc.setdefault(login.lower(), {
                "login": login, "repos": set(), "hashes": set()})
            entry["repos"].add(repo.full_name)
            entry["hashes"].update(repo.signal_hashes)
        if i % 20 == 0:
            emit(f"  fanout: {i}/{len(work)} repos -> {len(acc)} candidates")
    emit(f"  fanout: {len(work)} repos read (page 1 only, 1 call each) -> "
         f"{len(acc)} distinct candidates")

    candidates = [
        FanoutCandidate(
            login=e["login"],
            via_repos=tuple(sorted(e["repos"], key=str.lower)),
            signal_hashes=tuple(sorted(e["hashes"])),
        )
        for _, e in sorted(acc.items())
    ]
    return candidates, len(work)
