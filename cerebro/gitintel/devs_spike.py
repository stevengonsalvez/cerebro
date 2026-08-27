"""F066 — the sanity-gate spike: vault lane in, eyeballable top-20 out.

THE RISK GATE FOR THE WHOLE PROGRAMME. If a sane top-20 cannot be produced from the
vault lane, nothing downstream is worth building. This module runs the thinnest end-to-
end path that proves it on real data, writes the artifacts a human eyeballs, and exits
non-zero if the mechanical predicate fails.

    seed_repos -> resolve_owner -> pool_metrics -> shape -> flags -> admit
                                                                      |
                             order_by_consistency -> top20 -> sanity_check -> artifacts

WHAT IT DELIBERATELY DOES NOT DO. It emits ZERO `Signal` objects — this module does not
import `Signal` and a test asserts it. `crackscan.fetch()` already leaks a
`crackscan/considered` Signal for every merely-considered candidate, which is how
un-admitted names reach the vault today; gating that is e03's job and this epic is bound
not to make it worse. It writes nothing under the vault path, nothing to the roster, and
nothing to `cracked_devs.yaml`. It does not import the condemned scorer.

It also never writes a verdict. Every flagged account gets a PASTE-READY yaml block in
both directions and a human pastes one: auto-generating denylist entries would convert
flag-for-review back into auto-exclude with extra steps.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import (
    admission,
    denylist,
    facets as facets_mod,
    fanout,
    fork_provenance,
    gharchive,
    pool,
    shape,
    vault_seed,
)
from .admission import Flag
from .owner_resolve import VENDOR_ORGS

TOP_N = 20
WINDOWS = (7, 30, 90)

#: Every lane the spike can run, in the order the census prints them.
LANES = ("vault", "fanout", "roster")

#: The e02 knob defaults, restated here so the library has the same envelope as the CLI
#: and a caller that imports `run` directly cannot silently get an unbounded one.
DEFAULT_FANOUT_REPOS = 60
DEFAULT_REST_BUDGET = 1400
DEFAULT_FORK_BUDGET = fork_provenance.DEFAULT_FORK_BUDGET

#: The whole-run REST ceiling. EVERY COMPONENT MEASURED 2026-08-27, and two of them
#: falsify the estimates the plan was written against:
#:
#:   owner resolution      338   plan estimated ~175-260. e01 printed a structural zero,
#:                               so nobody had ever measured it until the counter existed.
#:   fan-out               60    1 call per repo, page 1 only. As planned.
#:   roster                4     handle-carrying devs only.
#:   paid pre-filter    <=1400   PLAN ESTIMATED 400. Measured: 60 seed repos surface
#:                               2,452 distinct contributors, of whom 1,252 clear the
#:                               5-active-day floor and therefore genuinely need the
#:                               humanness call. 400 truncated 852 of them.
#:   fork provenance     <=300   unchanged knob.
#:                       ------
#:                        2,102  against 5,000/hr, and inside the 2,400 kill criterion.
#:
#: THE AMENDMENT IS RECORDED RATHER THAN ABSORBED. The plan's 400 was written before the
#: fan-out lane existed and before anything in this repo could count a REST call; the
#: real number is a fact about how many contributors 60 vault-cited repos have. Lowering
#: `--fanout-repos` is the knob that brings it down, and it costs pool size.
REST_CALLS_CAP = 2200

#: WARNING-ONLY, never a failure. The Court ruled that name-pattern filtering is
#: provably insufficient — `github-actions[bot]` is caught by the `[bot]` suffix, but
#: the mass-repo spammers and service accounts that actually reached the top of a volume
#: ranking were not, and every bad account found so far was found by SHAPE or by a person
#: looking. A `-bot`/`-ci` suffix is therefore worth routing into the eyeball queue and
#: is worth nothing as a gate: it both misses automation and would silently drop a human
#: whose login happens to end that way. Failing on it would re-create name filtering as
#: an auto-exclude, which is exactly what the ruling forbids.
SUSPECT_LOGIN_SUFFIXES = ("-bot", "_bot", "-ci", "_ci", "-actions", "-automation",
                          "-runner", "-service", "-app")


@dataclass
class DevRecord:
    """One candidate, in the roadmap's SCHEMA FREEZE shape.

    `repos` ships EMPTY with an explicit `repos_populated: false` marker. Every element
    field the freeze names (title, description, language, topics, stars_fact, last_push)
    comes from REST repo endpoints this epic deliberately does not call. `[]` on its own
    is indistinguishable from "this developer has no repos" and would publish an empty
    repo card as a fact about a named human; the marker is a typed placeholder e03
    populates and e04 branches on.
    """

    login: str
    name: str | None
    discovered_via: str
    provenance: list[str]
    windows: dict
    pushes_per_week: list[int]
    automation: dict
    low_n: bool
    admitted: bool
    reasons: list[str]
    #: Every lane that produced this person. `discovered_via` is the single precedence
    #: winner; this is the whole set, so the precedence stays auditable on the page.
    discovered_via_all: list[str] = field(default_factory=list)
    #: The repos that put this person in the pool. A fan-out candidate is here because of
    #: a REPO, not because a signal note named them, and the profile copy has to be able
    #: to say that hop honestly rather than implying a personal citation.
    provenance_repos: list[str] = field(default_factory=list)
    #: F023/F019 display facts per window. NEVER a sort key on the index.
    facets: dict = field(default_factory=dict)
    repos: list = field(default_factory=list)
    repos_populated: bool = False
    generated_at: str = ""


@dataclass
class SanityResult:
    ok: bool
    failures: list[str]
    warnings: list[str]


def sanity_check(top, verdicts) -> SanityResult:
    """The mechanical half of the F066 gate. Names every offender; never guesses.

    This is the regression test for yesterday's discoveries. It can only test for shapes
    already known, which is exactly why the human eyeball is mandatory alongside it —
    every bad account found so far was found by a person looking, then encoded here.
    """
    failures: list[str] = []
    warnings: list[str] = []

    if not top:
        failures.append("ZERO rows in the top list — the pipeline produced nothing")
    elif len(top) < TOP_N:
        warnings.append(f"only {len(top)} rows, fewer than the {TOP_N} asked for")

    for rec in top:
        low = rec.login.lower()
        if low.endswith("[bot]"):
            failures.append(f"{rec.login}: a [bot] login reached the top list")
        if low in VENDOR_ORGS:
            failures.append(f"{rec.login}: a vendor org reached the top list")
        if low in verdicts.denied:
            failures.append(f"{rec.login}: carries a denied verdict "
                            f"({verdicts.denied[low].shape})")
        state = rec.automation.get("state")
        if state != "clear":
            failures.append(f"{rec.login}: automation state is {state!r}, not clear")

        # THE GATE THAT MAKES A TRUNCATED REST BUDGET SAFE INSTEAD OF MERELY VISIBLE.
        # Fan-out candidates below the activity floor never cost a humanness call, and
        # they cannot reach this list because the ordering is consistency-descending and
        # they have almost none. A candidate the REST BUDGET truncated is different: they
        # can be highly active and entirely unchecked. Publishing "this is a person"
        # without having looked is exactly the failure the verification doctrine calls
        # worse than no page, so it fails the gate rather than merely appearing in the
        # budget report. The fix is to raise `--rest-budget` and re-run.
        # FAIL-CLOSED, INCLUDING ON A MISSING MARKER. `prefilter` is a frozen field, so
        # a record without one is a producer defect, and treating "absent" as "fine"
        # would make the gate silently vacuous the day a new lane forgets to set it —
        # which is exactly how a gate becomes decoration.
        #
        # `curated_roster` PASSES, and that is not a softening. The gate catches "a call
        # was intended and never made"; a roster entry is a login a human typed into
        # `config/cracked_devs.yaml`, so a human did look and no call was ever owed. It
        # is also the only marker with no remedy — `--rest-budget` cannot buy a call the
        # pipeline never planned — so failing on it would be an unclearable stop on the
        # owner's own list. The marker still travels into the record, and the writer
        # still must not render it as a verified account.
        pre = rec.automation.get("prefilter")
        if pre in pool.PREFILTER_UNCHECKED or pre not in pool.PREFILTER_STATES:
            failures.append(
                f"{rec.login}: reached the top list marked {pre!r} — no humanness check "
                f"was ever made against this account, so publishing it as a person "
                f"publishes something nobody looked at. If the marker is a deferral, "
                f"raise --rest-budget and re-run; do not publish this list.")

        suffix = next((sfx for sfx in SUSPECT_LOGIN_SUFFIXES if low.endswith(sfx)), None)
        if suffix:
            warnings.append(
                f"{rec.login}: login ends in {suffix!r} — a bot-shaped name that carries "
                f"no [bot] suffix. Not a failure and never an auto-exclude (name-pattern "
                f"filtering is provably insufficient in both directions); eyeball it.")

    # WHOSE EYE. Charter success criterion 4 is "verified by eye", so a run has to say
    # which admissions rest on a verdict an agent recorded versus one the owner signed.
    # Warning, not failure: an agent-recorded verdict carries real evidence from a real
    # review and blocking on it would strand the epic, but the outstanding countersign
    # must be visible on every run rather than discovered at the F070 launch probe.
    unsigned = [(rec.login, entry) for rec in top
                for entry in [verdicts.cleared.get(rec.login.lower())]
                if entry is not None and not denylist.is_owner_signed(entry)]
    if unsigned:
        who = ", ".join(f"{login} (by {e.reviewed_by})" for login, e in unsigned)
        warnings.append(
            f"{len(unsigned)} of the top {len(top)} are admitted on an AGENT-recorded "
            f"`cleared:` verdict, not an owner-signed one: {who}. The mandated human "
            f"eyeball is owner-countersigned before launch (F070/e07).")

    return SanityResult(ok=not failures, failures=failures, warnings=warnings)


def _resolve_owners(seeds, client, log=print):
    """seed pairs -> {login: [signal hashes]}, org owners resolved to a human committer.

    REST is reserved for what only REST can do: org->human resolution (F002). Activity
    metrics come from the free ClickHouse lane, never from per-candidate REST.
    """
    from .owner_resolve import resolve_owner

    by_owner: dict[str, list] = {}
    for s in seeds:
        by_owner.setdefault(s.owner.lower(), []).append(s)

    out: dict[str, set] = {}
    repos: dict[str, set] = {}
    calls_before = getattr(client, "_calls", 0)
    for i, (_, group) in enumerate(sorted(by_owner.items()), 1):
        full = group[0].full_name
        try:
            login = resolve_owner(full, client)
        except Exception as exc:  # noqa: BLE001 — one bad repo must not sink the scan
            log(f"  resolve failed for {full}: {exc}")
            continue
        if not login:
            continue
        bucket = out.setdefault(login, set())
        repo_bucket = repos.setdefault(login, set())
        for s in group:
            bucket.update(s.signal_hashes)
            repo_bucket.add(s.full_name)
        if i % 25 == 0:
            log(f"  resolved {i}/{len(by_owner)} owners -> {len(out)} humans")
    log(f"  owner resolution: {len(by_owner)} owners -> {len(out)} humans "
        f"({getattr(client, '_calls', calls_before) - calls_before} REST calls)")
    return ({k: sorted(v) for k, v in out.items()},
            {k: sorted(v, key=str.lower) for k, v in repos.items()})


def _vault_lane(seeds, client, log=print):
    """The e01 lane, re-expressed as pool candidates so `assemble` can merge it.

    Unchanged in behaviour: the same `resolve_owner` walk, the same REST cost, the same
    provenance. What is new is that it now hands back `pool.Cand` objects carrying the
    seed repos alongside the signal hashes, because a three-lane pool has to say WHICH
    repo put somebody in it, not only that something did.
    """
    provenance, repos = _resolve_owners(seeds, client, log=log)
    cands = [
        pool.Cand(login=login, signal_hashes=tuple(hashes),
                  via_repos=tuple(repos.get(login, ())),
                  discovered_via="vault", name="", discovered_via_all=("vault",))
        for login, hashes in sorted(provenance.items(), key=lambda kv: kv[0].lower())
    ]
    return cands, provenance


def run(vault_path, out_dir, *, client, verdicts_path=denylist.DEFAULT_PATH,
        limit=TOP_N, log=print, transport=None, lanes=LANES,
        fanout_repos=DEFAULT_FANOUT_REPOS, rest_budget=DEFAULT_REST_BUDGET,
        fork_budget=DEFAULT_FORK_BUDGET):
    """The whole dry-run pipeline. Returns (SanityResult, top, all_records, paths).

    THE ORDER OF THE STAGES IS THE BUDGET. Free work first, paid work last, and the paid
    work only on candidates the free work has already shown are worth a call:

        vault seeds --+
        roster       -+--> assemble (free) --> ClickHouse, 3 scans (free)
        fan-out page 1 |                              |
        (1 call/repo) -+                              v
                                          activity floor (free)
                                                      |
                                                      v
                                         get_user pre-filter  <- the only paid step
                                                      |
                                                      v
                                   flags -> fork provenance on the FLAGGED only
                                                      |
                                                      v
                              admit -> order_by_consistency -> top -> sanity gate

    Nothing here writes to the vault, emits a `Signal`, or records a verdict.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    generated_at = datetime.now(timezone.utc).isoformat()
    lanes = tuple(x for x in LANES if x in set(lanes))
    if not lanes:
        raise ValueError(f"no lanes selected; choose from {LANES}")

    # ONE ACCOUNTANT. Every REST number in the artifact is a delta off these two, so no
    # lane can keep a private tally that disagrees with what actually left the process.
    calls_at_start = getattr(client, "_calls", 0)
    hits_at_start = getattr(client, "_cache_hits", 0)
    counter_is_real = hasattr(client, "_calls") and hasattr(client, "_cache_hits")

    verdicts = denylist.load(verdicts_path)
    log(f"verdicts: {len(verdicts.denied)} denied, {len(verdicts.cleared)} cleared")

    seeds = vault_seed.seed_repos(vault_path)
    owners = {s.owner.lower() for s in seeds}
    log(f"seed lane: {len(seeds)} owner/repo pairs across {len(owners)} distinct owners")

    census = {"lanes": lanes, "seed_repos": len(seeds), "seed_owners": len(owners)}

    # --- lane 1: the vault, unchanged from e01 ----------------------------
    vault_cands, provenance = ([], {})
    if "vault" in lanes:
        vault_cands, provenance = _vault_lane(seeds, client, log=log)
    census["vault_candidates"] = len(vault_cands)

    # --- lane 3: the roster, and the skips that make it auditable ---------
    roster_cands, roster_skipped = ([], [])
    if "roster" in lanes:
        roster_cands, roster_skipped = pool.roster_lane()
        log(f"roster lane: {len(roster_cands)} handle-carrying devs, "
            f"{len(roster_skipped)} skipped ({pool.NO_HANDLE})")
    census["roster_emitted"] = [c.login for c in roster_cands]
    census["roster_skipped"] = [{"name": s.name, "reason": s.reason} for s in roster_skipped]

    # --- lane 2: contributor fan-out, page 1 only -------------------------
    fanout_raw, fanout_repos_read = ([], 0)
    if "fanout" in lanes:
        fanout_raw, fanout_repos_read = fanout.fanout_lane(
            seeds, client, limit=fanout_repos, log=log)
    census["fanout_repos_read"] = fanout_repos_read
    census["fanout_raw_candidates"] = len(fanout_raw)

    # Fan-out candidates the vault or roster lane ALREADY anchored need no humanness
    # call: they were resolved by `resolve_owner`, or they are curated. Only genuinely
    # new logins reach the paid step, which is free dedup doing budget work.
    anchored = {pool.slug(c.login) for c in vault_cands} | {
        pool.slug(c.login) for c in roster_cands}
    fanout_known = [c for c in fanout_raw if pool.slug(c.login) in anchored]
    fanout_new = [c for c in fanout_raw if pool.slug(c.login) not in anchored]
    census["fanout_already_anchored"] = len(fanout_known)
    census["fanout_new_logins"] = len(fanout_new)

    # --- the free scan, over every login any lane produced ----------------
    scan_logins = sorted({pool.slug(c.login): c.login for c in
                          list(vault_cands) + list(roster_cands) + list(fanout_raw)}.values(),
                         key=str.lower)
    if not scan_logins:
        raise RuntimeError("every lane produced zero candidates — nothing to gate")

    sql_paths = []
    for w in WINDOWS:
        pth = out / f"devs-pool-{w}d-{stamp}.sql"
        pth.write_text(gharchive.render_sql(scan_logins, w), encoding="utf-8")
        sql_paths.append(pth)
    log(f"wrote the exact query bytes for {len(WINDOWS)} windows to {out}")

    metrics = gharchive.pool_metrics(scan_logins, windows=WINDOWS, transport=transport)
    active = sum(1 for m in metrics.values() if m[90].active_days > 0)
    log(f"gh archive: {len(metrics)} logins, {active} with 90d activity "
        f"({len(metrics) - active} zero-activity, which is a label case not a drop)")

    # --- the ONE paid step, on new fan-out logins only --------------------
    #
    # F063 work order: the seed repos the vault keeps returning to come first, so a run
    # that hits the cap spends its calls where the corpus points. It orders WORK.
    work_order = [c.login for c in sorted(
        fanout_new, key=lambda c: (-len(c.signal_hashes), pool.slug(c.login)))]
    pre = pool.paid_prefilter(fanout_new, metrics, client,
                              cap=rest_budget, order=work_order)
    log(f"pre-filter: {len(pre.kept)} human, {len(pre.rejected)} rejected, "
        f"{len(pre.deferred)} deferred (cost {pre.calls_used} REST calls"
        + (", TRUNCATED" if pre.truncated else "") + ")")
    census["prefilter_kept"] = len(pre.kept)
    census["prefilter_rejected"] = sorted(c.login for c in pre.rejected)
    census["prefilter_deferred"] = len(pre.deferred)
    census["prefilter_truncated"] = pre.truncated

    # ONLY the paid step writes into this map, and only about candidates it actually
    # considered. Everyone else gets their marker from `_prefilter_marker`, which reads
    # the lane rather than assuming one — see the docstring there for why a default of
    # `rest_verified` is a false claim about a real person.
    prefilter_state = {pool.slug(c.login): pool.PREFILTER_VERIFIED for c in pre.kept}
    for cand, reason in pre.deferred:
        prefilter_state[pool.slug(cand.login)] = reason

    # `FanoutCandidate` -> `pool.Cand`. The conversion happens HERE, after the paid
    # step, so the fan-out dataclass never has to carry a lane name and can stay the
    # deliberately narrow three-field record that has nowhere to put a commit count.
    fanout_cands = [
        pool.Cand(login=c.login, signal_hashes=c.signal_hashes, via_repos=c.via_repos,
                  discovered_via="fanout", name="", discovered_via_all=("fanout",))
        for c in list(fanout_known) + list(pre.kept) + [c for c, _ in pre.deferred]
    ]

    # --- F015: one person, one entry --------------------------------------
    pool_cands = pool.assemble(vault_cands, roster_cands, fanout_cands)
    collapsed = (len(vault_cands) + len(roster_cands) + len(fanout_cands)) - len(pool_cands)
    census["pool_size"] = len(pool_cands)
    census["dedup_collapses"] = collapsed
    census["by_lane"] = {
        lane: sum(1 for c in pool_cands if c.discovered_via == lane) for lane in LANES}
    census["multi_lane"] = sum(1 for c in pool_cands if len(c.discovered_via_all) > 1)
    log(f"dedup: {len(pool_cands)} distinct people, {collapsed} lane collapse(s)")

    # --- shapes, then fork provenance on the FLAGGED only -----------------
    budget = pool.Budget(
        rest_calls_cap=REST_CALLS_CAP,
        clickhouse_scans=len(WINDOWS),
        truncated=pre.truncated,
        skipped_logins=sum(1 for _c, r in pre.deferred if r == pool.PREFILTER_TRUNCATED),
        fork_calls_cap=int(fork_budget),
        prefilter_deferred=len(pre.deferred),
        prefilter_rejected=len(pre.rejected),
    )
    fork_bud = fork_provenance.ForkBudget(int(fork_budget))

    base_flags = {}
    for cand in pool_cands:
        m90 = metrics[_metric_key(metrics, cand.login)][90]
        base_flags[cand.login] = admission.flags(m90)

    # Flagged candidates in F063 recurrence order against the ONE shared ceiling.
    fork_shaped = [c for c in pool_cands
                   if any(f.name == "fork_farm" for f in base_flags[c.login])]
    fork_shaped.sort(key=lambda c: (-len(c.signal_hashes), pool.slug(c.login)))
    fork_evidence = {}
    for cand in fork_shaped:
        m90 = metrics[_metric_key(metrics, cand.login)][90]
        fork_evidence[cand.login] = fork_provenance.evidence(
            cand.login, m90, client, budget=fork_bud)
    budget.fork_calls_used = fork_bud.used
    budget.fork_budget_exhausted = fork_bud.exhausted and bool(fork_shaped)
    budget.fork_unevidenced = sum(1 for e in fork_evidence.values() if e.checked == 0)
    if fork_shaped:
        log(f"fork provenance: {len(fork_shaped)} fork-shaped candidates, "
            f"{fork_bud.used}/{fork_bud.cap} calls, "
            f"{budget.fork_unevidenced} left unevidenced (flags stand)")

    records: list[DevRecord] = []
    flags_by_login: dict[str, list[Flag]] = {}
    for cand in pool_cands:
        login = cand.login
        m = metrics[_metric_key(metrics, login)]
        m90 = m[90]
        ev = fork_evidence.get(login)
        fired = admission.name_fork_subshape(base_flags[login], ev)
        flags_by_login[login] = fired
        state = admission.automation_state(m90, login, verdicts)
        verdict = admission.admit(admission.Candidate(
            login=login,
            signal_hashes=cand.signal_hashes,
            active_days_90d=m90.active_days,
            active_days_30d=m[30].active_days,
            automation=state,
        ))
        cleared_by = verdicts.cleared.get(login.lower())
        records.append(DevRecord(
            login=login,
            name=cand.name or None,
            discovered_via=cand.discovered_via,
            discovered_via_all=list(cand.discovered_via_all),
            provenance=list(cand.signal_hashes),
            provenance_repos=list(cand.via_repos),
            windows={f"{w}d": _window_dict(m[w]) for w in WINDOWS},
            pushes_per_week=list(m90.pushes_per_week),
            facets=facets_mod.facets({w: m[w] for w in WINDOWS}),
            automation={
                "state": state,
                "push_per_day": round(shape.push_per_active_day(m90), 4),
                "not_owned_ratio": round(shape.not_owned_ratio(m90), 4),
                "basename_concentration": round(shape.basename_concentration(m90), 4),
                "repo_per_active_day": round(shape.repo_per_active_day(m90), 4),
                "shapes": [f.name for f in fired],
                "shape_evidence": [f.evidence for f in fired],
                "cleared_by": cleared_by.reviewed_by if cleared_by else None,
                "cleared_on": cleared_by.reviewed_on if cleared_by else None,
                "fork_provenance": ev.to_dict() if ev else None,
                "prefilter": _prefilter_marker(cand, prefilter_state),
            },
            low_n=verdict.low_n,
            admitted=verdict.admitted,
            reasons=list(verdict.reasons),
            generated_at=generated_at,
        ))

    admitted = [r for r in records if r.admitted]
    ordered = admission.order_by_consistency([_OrderKey(r) for r in admitted])
    top = [k.rec for k in ordered][:limit]
    log(f"admission: {len(admitted)} of {len(records)} admitted, "
        f"top {len(top)} by consistency")

    budget.rest_calls_used = getattr(client, "_calls", calls_at_start) - calls_at_start
    budget.rest_cache_hits = getattr(client, "_cache_hits", hits_at_start) - hits_at_start
    if not counter_is_real:
        log("WARNING: the client has no REST counter — every budget number is unmeasured")
    log(f"budget: {budget.rest_calls_used}/{budget.rest_calls_cap} REST calls, "
        f"{budget.rest_cache_hits} cache hits, {budget.clickhouse_scans} ClickHouse scans")

    result = sanity_check(top, verdicts)

    top_path = out / f"devs-top20-{stamp}.md"
    body = _render_top(top, stamp, generated_at, lanes)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    top_path.write_text(body + f"\nartifact-hash: {digest}\n", encoding="utf-8")

    queue_path = out / f"devs-flagqueue-{stamp}.md"
    queue_path.write_text(
        _render_queue(records, flags_by_login, verdicts, stamp), encoding="utf-8")

    census_path = out / f"devs-lanecensus-{stamp}.md"
    census_path.write_text(
        _render_census(census, budget, roster_skipped, stamp), encoding="utf-8")

    budget_path = out / f"devs-budget-{stamp}.json"
    budget_path.write_text(
        json.dumps(budget.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    json_path = out / f"devs-run-{stamp}.json"
    json_path.write_text(
        json.dumps([asdict(r) for r in records], indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    paths = {"top": top_path, "queue": queue_path, "json": json_path,
             "census": census_path, "budget": budget_path,
             "sql": sql_paths, "hash": digest}
    return result, top, records, paths


def _metric_key(metrics: dict, login: str) -> str:
    """`pool_metrics` keys on the login it was GIVEN; the pool may hold a different
    casing after dedup precedence. Resolve case-insensitively rather than KeyError on a
    person whose roster casing differs from the archive's."""
    if login in metrics:
        return login
    low = login.lower()
    for k in metrics:
        if k.lower() == low:
            return k
    raise KeyError(login)


@dataclass
class _OrderKey:
    """Adapts a DevRecord to what order_by_consistency reads, without giving the record
    itself sortable volume fields."""

    rec: DevRecord

    @property
    def login(self):
        return self.rec.login

    @property
    def active_days_90d(self):
        return self.rec.windows["90d"]["active_days"]

    @property
    def active_days_30d(self):
        return self.rec.windows["30d"]["active_days"]


def _prefilter_marker(cand, prefilter_state: dict) -> str:
    """Which humanness evidence, if any, actually exists for this person.

    NOT A DEFAULT-TO-VERIFIED LOOKUP. `rest_verified` is a claim that a real
    `GET /users/{login}` came back a real person, so it may only be written where a call
    really happened:

        fan-out, new login   -> the paid step ran; `prefilter_state` holds the truth,
                                which is `rest_verified` OR one of the two deferrals
        vault lane           -> `resolve_owner` already put every candidate through
                                `is_human` to produce the login at all, so the call
                                happened and `rest_verified` is earned
        roster only          -> NO call was ever made. `curated_roster`.

    The third case is why this is a function. A fan-out candidate can be "already
    anchored" by the ROSTER rather than by the vault, and the roster is a hand-written
    yaml file, not an API result; a plain `dict.get(login, PREFILTER_VERIFIED)` labelled
    those accounts verified and put a verification claim into a record about a named
    human that nothing had verified.
    """
    got = prefilter_state.get(pool.slug(cand.login))
    if got is not None:
        return got
    if "vault" in cand.discovered_via_all:
        return pool.PREFILTER_VERIFIED
    return pool.PREFILTER_ROSTER


def _window_dict(m) -> dict:
    return {
        "pushes": m.pushes,
        "distinct_repos": m.distinct_repos,
        "active_days": m.active_days,
        "repos_not_owned": m.repos_not_owned,
        "not_owned_basenames": m.not_owned_basenames,
        # F019's third term. Additive to the e01 freeze, and a deliberate, recorded
        # change: `tests/test_schema_freeze.py` asserts the window key set by EXACT
        # equality, so it moves in the same commit as this line.
        "not_owned_owners": m.not_owned_owners,
    }


def _render_top(top, stamp, generated_at, lanes=("vault",)) -> str:
    lines = [
        f"# devs top-{TOP_N} — {', '.join(lanes)} lane(s) — {stamp}",
        "",
        f"generated_at: {generated_at}",
        "Ordered by CONSISTENCY (active days in 90d). There is no score and no ranking",
        "number: this is a facet sort, and volume ordering is banned because it is",
        "empirically INVERTED, not merely noisy.",
        "",
        "| # | login | profile | 7d | 30d | 90d | pushes 90d | repos | not-owned | basenames | conc | push/day | automation | signals | low-n |",
        "|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|---|",
    ]
    for i, r in enumerate(top, 1):
        w = r.windows
        a = r.automation
        state = a["state"]
        if state == "clear" and a["shapes"]:
            state = (f"clear (cleared by {a['cleared_by']} {a['cleared_on']}; "
                     f"fired {', '.join(a['shapes'])})")
        lines.append(
            f"| {i} | {r.login} | https://github.com/{r.login} | "
            f"{w['7d']['active_days']} | {w['30d']['active_days']} | {w['90d']['active_days']} | "
            f"{w['90d']['pushes']} | {w['90d']['distinct_repos']} | "
            f"{w['90d']['repos_not_owned']} | {w['90d']['not_owned_basenames']} | "
            f"{a['basename_concentration']:.4f} | {a['push_per_day']:.2f} | "
            f"{state} | {len(r.provenance)} | {'YES' if r.low_n else '-'} |"
        )
    lines += ["", "## provenance (why each account is here at all)", "",
              "A `fanout` entry is here because of a REPO the vault cited, one hop away.",
              "The vault did not name the person. That distinction is recorded rather",
              "than smoothed over, because a profile page must not imply a citation",
              "nobody made.", ""]
    for i, r in enumerate(top, 1):
        via = "/".join(r.discovered_via_all) or r.discovered_via
        lines.append(f"{i}. **{r.login}** — discovered via {via} — "
                     f"{len(r.provenance)} vault signal note(s): "
                     f"{', '.join(r.provenance[:6])}"
                     + (" ..." if len(r.provenance) > 6 else ""))
        if r.provenance_repos:
            lines.append(f"    - via repo(s): {', '.join(r.provenance_repos[:6])}"
                         + (" ..." if len(r.provenance_repos) > 6 else ""))
    return "\n".join(lines) + "\n"


def _render_queue(records, flags_by_login, verdicts, stamp) -> str:
    unresolved = [r for r in records
                  if r.automation["state"] == "flagged"]
    cleared = [r for r in records
               if r.automation["state"] == "clear" and r.automation["shapes"]]
    excluded = [r for r in records if r.automation["state"] == "excluded"]

    lines = [
        f"# devs flag queue — {stamp}",
        "",
        "Every account below fired at least one automation SHAPE. A flag is a request",
        "for human review, never a verdict: nothing here has been excluded by",
        "arithmetic. Paste ONE of the two blocks per account into",
        "`config/devs_denylist.yaml` and commit it. A decision recorded anywhere else",
        "is not a decision: nothing loads it, and the account is re-flagged identically",
        "on the next run.",
        "",
        f"## unresolved — {len(unresolved)} account(s) awaiting a verdict",
        "",
    ]
    if not unresolved:
        lines.append("_(empty — every flagged account carries a committed verdict)_")
        lines.append("")
    for r in unresolved:
        a = r.automation
        w = r.windows["90d"]
        lines += [
            f"### {r.login}  —  https://github.com/{r.login}",
            "",
            f"- shapes fired: {', '.join(a['shapes'])}",
        ]
        for ev in a["shape_evidence"]:
            lines.append(f"- evidence: {ev}")
        fp = a.get("fork_provenance")
        if fp is not None:
            lines.append(f"- fork provenance: {_fork_line(fp)}")
            if fp.get("sampled"):
                lines.append(f"  - sampled: {', '.join(fp['sampled'])}")
            if fp.get("upstreams"):
                lines.append(f"  - upstream(s): {', '.join(fp['upstreams'])}")
            if fp.get("checked") == 0:
                lines.append("  - **LEFT UNEVIDENCED** by an exhausted fork budget. This "
                             "is NOT a clean flag: nobody looked. Raise `--fork-budget` "
                             "and re-run before deciding.")
        lines += [
            f"- 90d: {w['pushes']} pushes / {w['distinct_repos']} repos / "
            f"{w['active_days']} active days / {w['repos_not_owned']} not-owned "
            f"across {w['not_owned_basenames']} basenames",
            f"- provenance: {len(r.provenance)} vault signal(s): {', '.join(r.provenance[:4])}",
            "",
            "If AUTOMATION, paste into `denied:` —",
            "",
            "```yaml",
        ]
        lines += _verdict_block(r, "automation")
        lines += ["```", "", "If a REAL ENGINEER, paste into `cleared:` —", "", "```yaml"]
        lines += _verdict_block(r, "human", note="  # replace with the one-line human reason")
        lines += ["```", ""]

    lines += ["", f"## cleared by review — {len(cleared)} standing decision(s)", ""]
    for r in cleared:
        a = r.automation
        lines.append(f"- **{r.login}** fired {', '.join(a['shapes'])}, cleared by "
                     f"{a['cleared_by']} on {a['cleared_on']}")
    if not cleared:
        lines.append("_(none)_")

    lines += ["", f"## excluded by verdict — {len(excluded)} account(s)", ""]
    for r in excluded:
        e = verdicts.denied[r.login.lower()]
        lines.append(f"- **{r.login}** — {e.shape} — {e.evidence} "
                     f"(reviewed by {e.reviewed_by} on {e.reviewed_on})")
    if not excluded:
        lines.append("_(none)_")
    return "\n".join(lines) + "\n"


def _verdict_block(r, verdict: str, note: str = "") -> list[str]:
    a = r.automation
    w = r.windows["90d"]
    ev = (f"90d live {date.today().isoformat()}: {w['pushes']} pushes / "
          f"{w['distinct_repos']} distinct repos / {w['active_days']} active days / "
          f"{w['repos_not_owned']} not-owned across {w['not_owned_basenames']} "
          f"basenames / concentration {a['basename_concentration']:.4f} / "
          f"{a['push_per_day']:.2f} pushes per active day")
    return [
        f"  - login: {r.login}",
        f"    verdict: {verdict}",
        f"    shape: {a['shapes'][0] if a['shapes'] else 'none'}",
        f'    evidence: "{ev}"{note}',
        "    reviewed_by: owner",
        f"    reviewed_on: {date.today().isoformat()}",
    ]


def _fork_line(fp: dict) -> str:
    """One line of fork evidence for the queue, straight off the recorded dict."""
    if not fp or fp.get("checked", 0) == 0:
        return ("NOT gathered (budget exhausted or no archive sample) — the flag stands "
                "unevidenced")
    bits = [f"{fp['checked']} of {len(fp.get('sampled') or [])} sampled repos resolved"]
    if fp.get("own_upstream"):
        bits.append(f"{fp['own_upstream']} fork an upstream this account owns")
    if fp.get("third_party"):
        bits.append(f"{fp['third_party']} fork somebody else's repo")
    if fp.get("no_upstream"):
        bits.append(f"{fp['no_upstream']} are not forks at all")
    if fp.get("unresolved"):
        bits.append(f"{fp['unresolved']} unresolved (flag stands)")
    if fp.get("truncated"):
        bits.append("PARTIAL sample")
    return "; ".join(bits)


def _render_census(census: dict, budget, roster_skipped, stamp: str) -> str:
    """THE ARTIFACT THAT MAKES "NOBODY IS SUPPRESSED" AUDITABLE.

    Three things a reader must be able to check without grepping stdout: how many people
    each lane produced and how many collapsed, WHICH roster devs produced no pool entry
    and why, and what the run actually spent against every cap. All three are failure
    modes that look identical to success when they are only logged.
    """
    b = budget.to_dict()
    lines = [
        f"# devs lane census — {stamp}",
        "",
        f"lanes run: {', '.join(census['lanes'])}",
        "",
        "## what each lane produced",
        "",
        "| lane | candidates | note |",
        "|---|--:|---|",
        f"| vault | {census.get('vault_candidates', 0)} | "
        f"{census['seed_repos']} repos across {census['seed_owners']} owners, "
        f"owners resolved to humans |",
        f"| fanout | {census.get('fanout_raw_candidates', 0)} | "
        f"{census.get('fanout_repos_read', 0)} repos read, page 1 only, 1 REST call each |",
        f"| roster | {len(census.get('roster_emitted') or [])} | "
        f"handle-carrying devs from config/cracked_devs.yaml |",
        "",
        f"- fan-out candidates already anchored by another lane: "
        f"{census.get('fanout_already_anchored', 0)} (no REST call spent)",
        f"- genuinely new fan-out logins: {census.get('fanout_new_logins', 0)}",
        f"- pre-filter: {census.get('prefilter_kept', 0)} human, "
        f"{len(census.get('prefilter_rejected') or [])} rejected, "
        f"{census.get('prefilter_deferred', 0)} deferred below the activity floor",
        f"- **pool after dedup: {census.get('pool_size', 0)} distinct people** "
        f"({census.get('dedup_collapses', 0)} lane collapse(s), "
        f"{census.get('multi_lane', 0)} found by more than one lane)",
        "",
        "### discovered_via, after precedence",
        "",
    ]
    for lane, n in (census.get("by_lane") or {}).items():
        lines.append(f"- `{lane}`: {n}")

    lines += [
        "",
        "## the roster, all of it",
        "",
        "F008's ruling is that a roster dev is ALWAYS PROFILED, which is a statement",
        "about suppression. A dev with no `github:` handle is not suppressed — they are",
        "unrepresentable in a login-keyed pool — and the difference is only legible if",
        "the run names them. Every roster dev appears below, emitted or skipped.",
        "",
        "| dev | handle | in the pool |",
        "|---|---|---|",
    ]
    for login in census.get("roster_emitted") or []:
        lines.append(f"| {login} | `{login}` | yes |")
    for skip in roster_skipped:
        lines.append(f"| {skip.name} | — | no — {skip.reason} |")
    lines += [
        "",
        "Adding a handle is an OWNER EDIT to `config/cracked_devs.yaml`. The code never",
        "guesses one from an X handle or a display name: that would attach a published",
        "profile to an account no human confirmed belongs to that person.",
        "",
        "## budget, actual against cap",
        "",
        "| meter | used | cap |",
        "|---|--:|--:|",
        f"| REST calls | {b['rest_calls_used']} | {b['rest_calls_cap']} |",
        f"| REST cache hits | {b['rest_cache_hits']} | — |",
        f"| ClickHouse scans | {b['clickhouse_scans']} | 3 |",
        f"| fork provenance calls | {b['fork_calls_used']} | {b['fork_calls_cap']} |",
        "",
    ]
    if b["truncated"]:
        lines.append(f"- **REST BUDGET TRUNCATED**: {b['skipped_logins']} candidate(s) "
                     f"were never humanness-checked. They are in the pool, labelled, and "
                     f"not silently dropped.")
    else:
        lines.append("- REST budget not truncated.")
    if b["fork_budget_exhausted"]:
        lines.append(f"- **FORK BUDGET EXHAUSTED**: {b['fork_unevidenced']} flagged "
                     f"candidate(s) left unevidenced. Their flags STAND unchanged — a "
                     f"budget running out never clears anybody.")
    else:
        lines.append("- Fork budget not exhausted.")
    lines += [
        f"- {b['prefilter_deferred']} candidate(s) deferred below the activity floor: "
        f"no REST call was spent on them. Deferring a call is not suppression.",
        f"- {b['prefilter_rejected']} candidate(s) rejected by the humanness pre-filter.",
        "",
    ]
    rejected = census.get("prefilter_rejected") or []
    if rejected:
        lines += ["### rejected by the humanness pre-filter", "",
                  "Named, not silently dropped, so a wrong rejection is reviewable.", ""]
        lines += [f"- {r}" for r in rejected]
        lines.append("")
    return "\n".join(lines) + "\n"
