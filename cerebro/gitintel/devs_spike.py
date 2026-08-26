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

from . import admission, denylist, gharchive, shape, vault_seed
from .admission import Flag
from .owner_resolve import VENDOR_ORGS

TOP_N = 20
WINDOWS = (7, 30, 90)


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
        for s in group:
            bucket.update(s.signal_hashes)
        if i % 25 == 0:
            log(f"  resolved {i}/{len(by_owner)} owners -> {len(out)} humans")
    log(f"  owner resolution: {len(by_owner)} owners -> {len(out)} humans "
        f"({getattr(client, '_calls', calls_before) - calls_before} REST calls)")
    return {k: sorted(v) for k, v in out.items()}


def run(vault_path, out_dir, *, client, verdicts_path=denylist.DEFAULT_PATH,
        limit=TOP_N, log=print, transport=None):
    """The whole dry-run pipeline. Returns (SanityResult, top, all_records, paths)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    generated_at = datetime.now(timezone.utc).isoformat()

    verdicts = denylist.load(verdicts_path)
    log(f"verdicts: {len(verdicts.denied)} denied, {len(verdicts.cleared)} cleared")

    seeds = vault_seed.seed_repos(vault_path)
    owners = {s.owner.lower() for s in seeds}
    log(f"seed lane: {len(seeds)} owner/repo pairs across {len(owners)} distinct owners")

    provenance = _resolve_owners(seeds, client, log=log)
    logins = sorted(provenance)
    if not logins:
        raise RuntimeError("owner resolution produced zero humans — nothing to gate")

    sql_paths = []
    for w in WINDOWS:
        p = out / f"devs-pool-{w}d-{stamp}.sql"
        p.write_text(gharchive.render_sql(logins, w), encoding="utf-8")
        sql_paths.append(p)
    log(f"wrote the exact query bytes for {len(WINDOWS)} windows to {out}")

    metrics = gharchive.pool_metrics(logins, windows=WINDOWS, transport=transport)
    active = sum(1 for m in metrics.values() if m[90].active_days > 0)
    log(f"gh archive: {len(metrics)} logins, {active} with 90d activity "
        f"({len(metrics) - active} zero-activity, which is a label case not a drop)")

    records: list[DevRecord] = []
    flags_by_login: dict[str, list[Flag]] = {}
    for login in logins:
        m = metrics[login]
        m90 = m[90]
        fired = admission.flags(m90)
        flags_by_login[login] = fired
        state = admission.automation_state(m90, login, verdicts)
        cand = admission.Candidate(
            login=login,
            signal_hashes=tuple(provenance[login]),
            active_days_90d=m90.active_days,
            active_days_30d=m[30].active_days,
            automation=state,
        )
        verdict = admission.admit(cand)
        cleared_by = verdicts.cleared.get(login.lower())
        records.append(DevRecord(
            login=login,
            name=None,
            discovered_via="vault",
            provenance=list(provenance[login]),
            windows={f"{w}d": _window_dict(m[w]) for w in WINDOWS},
            pushes_per_week=list(m90.pushes_per_week),
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
            },
            low_n=verdict.low_n,
            admitted=verdict.admitted,
            reasons=list(verdict.reasons),
            generated_at=generated_at,
        ))

    admitted = [r for r in records if r.admitted]
    ordered = admission.order_by_consistency(
        [_OrderKey(r) for r in admitted])
    top = [k.rec for k in ordered][:limit]
    log(f"admission: {len(admitted)} of {len(records)} admitted, "
        f"top {len(top)} by consistency")

    result = sanity_check(top, verdicts)

    top_path = out / f"devs-top20-{stamp}.md"
    body = _render_top(top, stamp, generated_at)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    top_path.write_text(body + f"\nartifact-hash: {digest}\n", encoding="utf-8")

    queue_path = out / f"devs-flagqueue-{stamp}.md"
    queue_path.write_text(
        _render_queue(records, flags_by_login, verdicts, stamp), encoding="utf-8")

    json_path = out / f"devs-run-{stamp}.json"
    json_path.write_text(
        json.dumps([asdict(r) for r in records], indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    paths = {"top": top_path, "queue": queue_path, "json": json_path,
             "sql": sql_paths, "hash": digest}
    return result, top, records, paths


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


def _window_dict(m) -> dict:
    return {
        "pushes": m.pushes,
        "distinct_repos": m.distinct_repos,
        "active_days": m.active_days,
        "repos_not_owned": m.repos_not_owned,
        "not_owned_basenames": m.not_owned_basenames,
    }


def _render_top(top, stamp, generated_at) -> str:
    lines = [
        f"# devs top-{TOP_N} — vault lane — {stamp}",
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
    lines += ["", "## provenance (why each account is here at all)", ""]
    for i, r in enumerate(top, 1):
        lines.append(f"{i}. **{r.login}** — {len(r.provenance)} vault signal note(s): "
                     f"{', '.join(r.provenance[:6])}"
                     + (" ..." if len(r.provenance) > 6 else ""))
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
