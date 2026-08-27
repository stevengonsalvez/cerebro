"""F037 — `Devs/<login>.md`: the record, serialised.

THIS IS NOT `sink/entities.py::developer_markdown` AND IT NEVER TOUCHES IT. That writer
is the condemned follower/star model the charter ordered REBUILT rather than patched; it
is duck-typed over a `profile` dict of exactly the fields the devs lane spent an epic
removing. A test asserts this module does not import it.

WHY THE YAML IS HAND-EMITTED AND NOT `yaml.safe_dump`. Three independent reasons, each
of which would show up as a wrong page about a named human:

  1. `safe_dump` ALPHABETISES keys, destroying the contract order the site's loader
     documents and the diff stability the public vault's git history depends on.
  2. It emits its own float repr, so a small value reaches YAML as `1e-05`, which
     js-yaml hands to the site as the STRING "1e-05" and the site's `asFloat` throws.
  3. It leaves `generated_at` unquoted, and js-yaml inside gray-matter coerces an
     unquoted ISO timestamp to a JS `Date` — the exact defect `lib/vault/weekly.ts`'s
     `dateOnly()` already exists to kill.

EVERY STRING SCALAR IS DOUBLE-QUOTED, AND THAT IS A CORRECTNESS RULE, NOT A STYLE.
GitHub logins include `no`, `on`, `y` and `NO`, which YAML 1.1 parses as booleans, and
they include all-digit logins: `1105623876` and `245678000000` are both in today's
publish set. Unquoted they become integers, and the site compares `String(data.login)`
against the filename. The 16-hex provenance hashes carry the same hazard at roughly
1 in 1,845 per hash (`(10/16)**16`); today's 236 distinct hashes happen to contain no
all-digit one, so that is a LATENT failure waiting on a future day's corpus rather than
a present one. Quoting at the emitter kills both, and a hostile fixture proves it.

THE BODY IS FOR A HUMAN WITH OBSIDIAN OPEN. The site's loader never destructures it
(`readDevFile` binds `data` only), so nothing on a published page can originate here. It
carries one factual sentence about public push activity, in the charter's mandated
register: describe the activity, never judge the person.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..gitintel import facets as facets_mod

#: The 16 frozen top-level keys, in the order the site's serialization contract lists
#: them (`DEV_SNAKE` then the one CONSUMED key). `tests/test_devs_render.py` asserts this
#: tuple's SET equals `devs_spike.DevRecord.__dataclass_fields__`, so a producer field
#: added without a serializer slot is a build failure rather than a silently missing key
#: in a note about a named person.
FRONTMATTER_KEYS = (
    "login",
    "name",
    "discovered_via",
    "discovered_via_all",
    "provenance_repos",
    "admitted",
    "low_n",
    "repos_populated",
    "generated_at",
    "provenance",
    "pushes_per_week",
    "windows",
    "automation",
    "facets",
    "reasons",
    "repos",
)

#: The three frozen observation windows, emitted in this order and quoted so an emitter
#: change cannot turn `"7d"` into something a YAML parser reads as anything else.
WINDOW_KEYS = ("7d", "30d", "90d")

#: RENDER ORDER FOR EVERY NESTED SHAPE, AND WHY IT IS DECLARED RATHER THAN INHERITED.
#: The same record reaches this writer two ways: straight off the producer, whose dicts
#: are in construction order, and deserialised from a run json written with
#: `sort_keys=True`, whose dicts are alphabetical. Emitting in the input's own order
#: would make those two produce DIFFERENT BYTES for the same facts, which turns every
#: `apply()` comparison into a false "changed" and hands the public vault a full-corpus
#: commit for nothing. Any key not named here is emitted after the named ones, sorted,
#: so an unknown shape is still deterministic instead of merely undefined.
_WINDOW_BODY = ("pushes", "distinct_repos", "pushes_per_repo", "active_days",
                "repos_not_owned", "not_owned_basenames", "not_owned_owners")
_AUTOMATION = ("state", "push_per_day", "repo_per_active_day", "not_owned_ratio",
               "basename_concentration", "shapes", "shape_evidence", "cleared_by",
               "cleared_on", "fork_provenance", "prefilter")
_FORK = ("checked", "own_upstream", "third_party", "no_upstream", "unresolved",
         "truncated", "sampled", "upstreams")
_REPO = ("name", "title", "description", "language", "topics", "stars_fact",
         "first_seen", "last_push")

PREFERRED_ORDER = {
    "windows": WINDOW_KEYS,
    "facets": WINDOW_KEYS,
    "7d": _WINDOW_BODY,
    "30d": _WINDOW_BODY,
    "90d": _WINDOW_BODY,
    "automation": _AUTOMATION,
    "fork_provenance": _FORK,
    #: `repos` names a LIST, so this is the order of each element's own mapping.
    "repos": _REPO,
}

#: The line `generated_at` occupies, used by the unchanged-note comparison in `apply()`:
#: a note whose ONLY difference is the timestamp is not a change.
TIMESTAMP_KEY = "generated_at"


# --- scalars -----------------------------------------------------------------

def _q(value) -> str:
    """A YAML double-quoted scalar: backslash and quote escaped, whitespace collapsed.

    Collapsing whitespace is what makes the escape set small enough to be obviously
    correct. With no newline, tab or carriage return left in the string, `\\` and `"`
    are the only two characters a double-quoted YAML scalar can be broken by, and both
    are escaped here. A repo description containing `---`, a colon or a quote is
    therefore inert.
    """
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _null_or_q(value) -> str:
    """`null` for a genuine absence, a quoted string otherwise.

    An empty string is NOT an absence and is not coerced to one: `name: ""` and
    `name: null` mean different things on a page about a person, and only the record
    knows which one is true.
    """
    return "null" if value is None else _q(value)


def _num(value) -> str:
    """Ints bare, floats at four fixed decimal places, booleans never reaching here.

    FOUR DECIMALS AND NEVER `repr`. The producer rounds every shape metric to 4, so this
    is lossless on real records, and fixed-point notation is the only form that cannot
    reach YAML in exponent form.
    """
    if isinstance(value, bool):  # bool is an int subclass; it must not fall through
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return f"{round(float(value), 4):.4f}"


def _scalar(value) -> str:
    """Any leaf value. Booleans before ints, because `bool` IS an `int` in Python and a
    `True` that fell through to `_num` would be emitted as `1`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _num(value)
    return _null_or_q(value)


# --- collections --------------------------------------------------------------

def _ordered(key: str, mapping: dict):
    """`mapping`'s items in the declared order for `key`, unknown keys sorted after."""
    want = PREFERRED_ORDER.get(key, ())
    named = [k for k in want if k in mapping]
    rest = sorted(k for k in mapping if k not in set(want))
    return [(k, mapping[k]) for k in named + rest]


def _emit(key: str, value, indent: int) -> list[str]:
    """One frontmatter entry, as lines. Recurses for the nested shapes."""
    pad = " " * indent
    rendered_key = _q(key) if _needs_quoting(key) else key
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{rendered_key}: {{}}"]
        lines = [f"{pad}{rendered_key}:"]
        for k, v in _ordered(key, value):
            lines += _emit(k, v, indent + 2)
        return lines
    if isinstance(value, (list, tuple)):
        return _emit_list(key, list(value), indent)
    return [f"{pad}{rendered_key}: {_scalar(value)}"]


def _emit_list(key: str, values: list, indent: int) -> list[str]:
    """Ints flow, everything else block. Two forms, no judgement call at the call site.

    `pushes_per_week` is the 13-element integer series the site asserts the length of,
    and the contract calls it a flow sequence; a block sequence of 13 lines would also
    parse, but the contract is the contract. Strings and mappings go block so a long
    `shape_evidence` line stays readable in a diff, which is where a wrong number about
    a person is actually caught.
    """
    pad = " " * indent
    rendered_key = _q(key) if _needs_quoting(key) else key
    if not values:
        return [f"{pad}{rendered_key}: []"]
    if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return [f"{pad}{rendered_key}: [{', '.join(_num(v) for v in values)}]"]
    lines = [f"{pad}{rendered_key}:"]
    for v in values:
        if isinstance(v, dict):
            lines += _emit_mapping_item(key, v, indent + 2)
        else:
            lines.append(f"{pad}  - {_scalar(v)}")
    return lines


def _emit_mapping_item(key: str, mapping: dict, indent: int) -> list[str]:
    """One `- key: value` block-sequence entry, e.g. an element of `repos`."""
    pad = " " * indent
    items = _ordered(key, mapping)
    if not items:
        return [f"{pad}- {{}}"]
    out: list[str] = []
    for i, (k, v) in enumerate(items):
        rendered = _emit(k, v, indent + 2)
        if i == 0:
            out.append(f"{pad}- " + rendered[0].lstrip())
            out += rendered[1:]
        else:
            out += rendered
    return out


def _needs_quoting(key: str) -> bool:
    """Window keys (`7d`, `30d`, `90d`) and anything else a parser could reinterpret."""
    return not key.replace("_", "").isalpha()


# --- the note ------------------------------------------------------------------

def render(record: dict, *, timestamp: bool = True) -> str:
    """The whole note: frontmatter in contract order, then the body.

    `timestamp=False` renders `generated_at: ""` instead of the real value. That is the
    comparison form used by `apply()`: `generated_at` means "when these facts last
    CHANGED", so a note whose only difference is the stamp must be left alone rather
    than rewritten, or the public vault takes a 1,300-file commit every morning and its
    history stops meaning anything.
    """
    rec = dict(record)
    missing = [k for k in FRONTMATTER_KEYS if k not in rec]
    if missing:
        raise ValueError(
            f"devs record for {rec.get('login')!r} is missing frozen field(s) "
            f"{', '.join(missing)} — a note with a hole in it is a wrong statement "
            f"about a named person, not a partial one")
    extra = [k for k in rec if k not in FRONTMATTER_KEYS]
    if extra:
        raise ValueError(
            f"devs record for {rec.get('login')!r} carries unfrozen field(s) "
            f"{', '.join(sorted(extra))}. The site's loader asserts an EXACT key set at "
            f"every nesting level, so an additive producer field is a build-killing "
            f"throw there. Answer it in the roadmap as a coordination event first.")

    lines = ["---"]
    for key in FRONTMATTER_KEYS:
        value = rec[key]
        if key == TIMESTAMP_KEY and not timestamp:
            value = ""
        lines += _emit(key, value, 0)
    lines.append("---")
    return "\n".join(lines) + "\n" + _body(rec)


def _body(rec: dict) -> str:
    """One heading, one factual sentence, one link. No adjective about the person.

    The sentence is `facets.describe_breadth_and_depth`, reused rather than restated so
    the register the charter mandated is enforced in one place: it describes public push
    activity and contains no comparative, no ranking word and no judgement.
    """
    w = rec["windows"]["90d"]
    sentence = facets_mod.describe_breadth_and_depth(_Window90(
        pushes=int(w["pushes"]),
        distinct_repos=int(w["distinct_repos"]),
        active_days=int(w["active_days"]),
    ))
    login = str(rec["login"])
    return (f"\n# {login}\n\n"
            f"{sentence} of public GitHub push activity.\n\n"
            f"https://github.com/{login}\n")


class _Window90:
    """The three numbers `describe_breadth_and_depth` reads, off a serialised record.

    A plain adapter, and deliberately not a dataclass: the no-composite sweep inspects
    dataclass field declarations in this lane, and this thing exists only to carry three
    integers from a dict into a duck-typed function.
    """

    window_days = 90

    def __init__(self, pushes: int, distinct_repos: int, active_days: int):
        self.pushes = pushes
        self.distinct_repos = distinct_repos
        self.active_days = active_days


# --- the write gate ------------------------------------------------------------
#
# THE WRITE GATE IS THE PUBLISH GATE, AND IT HAS SIX CLAUSES, NOT FIVE.
#
# `cerebro-vault` is a PUBLIC repository. A record written into `Devs/` is published data
# about a named human whether or not the site renders a page from it. So the writer does
# not write records the site would withhold, and WITHHELD MEANS NOT WRITTEN: the flagged,
# the excluded and the deferred stay in the operator's gitignored audit trail under
# `logs/devs/`, never in the vault.
#
#     publishable(r) := slug(r.login) not in optout                 CONSENT     (F049)
#                   AND slug(r.login) not in verdicts.denied        VERDICT     (F017)
#                   AND len(r.provenance) >= 1                      FLOOR 1     (Q7)
#                   AND r.automation.state == "clear"               TRI-STATE   (F037)
#                   AND r.automation.prefilter not in PREFILTER_UNCHECKED
#                   AND r.admitted
#
# WHY THE VERDICT CLAUSE IS NOT REDUNDANT WITH THE TRI-STATE CLAUSE. In a fresh run the
# `excluded` state is reachable only from `verdicts.denied` and the verdicts file is
# reloaded per run, so on the happy path the tri-state already covers it. But this
# writer's inputs are RECORDS, and a record deserialised from a run json written BEFORE a
# verdict landed carries the pre-verdict state. Measured, not hypothesised: `GCGH159` in
# the 2026-08-27 run artifact is `admitted: true` / `state: "clear"` /
# `prefilter: "rest_verified"` / provenance 1, and carries a `denied:` verdict recorded
# after that run. Without this clause the same run DELETES him (a denied verdict is a
# consent-class delete, which fires always) and RE-WRITES him from the same plan.
#
# It does not make a shape flag auto-exclude. It reads a RECORDED verdict, out of the
# same file `admission` reads, and nothing else. A `flagged` record with no verdict is
# withheld by the tri-state clause, unchanged.
#
# THE CLAUSE ORDER IS THE REPORT ORDER, AND IT IS DELIBERATE. Consent is evaluated FIRST
# so a person who asked to be removed is never characterised in the withheld report by a
# judgement about their account. The provenance floor is evaluated before `admitted` so
# the report names the FLOOR a record failed rather than the flat fact that it failed
# one: `t3dotgg` is `admitted: false` precisely BECAUSE of floor 1, and "not admitted"
# would hide the one thing an operator needs to know about him.

#: Reason strings, one per clause. Distinct on purpose: the withheld report groups by
#: these and an operator has to be able to tell a removal request from a floor.
REASON_OPTED_OUT = "opted out"
REASON_DENIED = "denied verdict"
REASON_PROVENANCE = "provenance floor"
REASON_NOT_ADMITTED = "not admitted"


def _field(record, name, default=None):
    """Read a field off a `DevRecord` or off the same record deserialised from json."""
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def slug(login: str) -> str:
    """The identity key. `pool.slug`, imported rather than restated."""
    from ..gitintel.pool import slug as pool_slug
    return pool_slug(login)


def publishable(record, *, optout=None, verdicts=None):
    """`(ok, reason)` for one record. `reason` is `""` when it is publishable.

    Reads `pool.PREFILTER_UNCHECKED` and the loaded `denied` set rather than restating
    either, so the vocabulary cannot drift from the producer's or from the site's.
    """
    from ..gitintel import pool

    key = slug(str(_field(record, "login", "")))
    if optout is not None and key in getattr(optout, "logins", frozenset()):
        return False, REASON_OPTED_OUT
    denied = getattr(verdicts, "denied", {}) or {}
    if key in denied:
        return False, REASON_DENIED
    if not (_field(record, "provenance") or []):
        return False, REASON_PROVENANCE
    automation = _field(record, "automation") or {}
    state = automation.get("state")
    if state != "clear":
        return False, f"automation: {state}"
    prefilter = automation.get("prefilter")
    if prefilter in pool.PREFILTER_UNCHECKED or prefilter not in pool.PREFILTER_STATES:
        return False, f"prefilter: {prefilter}"
    if not _field(record, "admitted"):
        return False, REASON_NOT_ADMITTED
    return True, ""


def publish_set(records, *, optout=None, verdicts=None):
    """Every record that passes all six clauses, input order preserved.

    Input order is preserved rather than re-sorted because the caller supplies the F063
    recurrence work order, and re-sorting here would silently spend a truncated repo
    budget somewhere else.
    """
    return [r for r in records
            if publishable(r, optout=optout, verdicts=verdicts)[0]]


def withheld(records, *, optout=None, verdicts=None):
    """`[(login, reason)]` for every record that did NOT pass, in input order."""
    out = []
    for rec in records:
        ok, reason = publishable(rec, optout=optout, verdicts=verdicts)
        if not ok:
            out.append((str(_field(rec, "login", "")), reason))
    return out


# --- the reconciling writer -----------------------------------------------------
#
# AN APPEND-ONLY WRITER CANNOT HONOUR AN OPT-OUT. If `Devs/` is only ever added to, a
# person who asks to be removed keeps their page for ever and charter outcome 4 is
# unmet. So this module OWNS `Devs/*.md` and nothing else: it computes a plan over
# {today's publish set} against {the notes already on disk}, and it touches no other path
# in the vault, ever.
#
# DELETIONS HAVE TWO SOURCES AND TWO RISK PROFILES, SO THEY GET TWO RULES.
#
#   CONSENT  a login in the opt-out file, or carrying a `denied:` verdict
#            -> executed ALWAYS. Including on a failed run. Uncapped.
#   CHURN    on disk, absent from today's publish set for any other reason
#            -> executed only on a HEALTHY run, and only under the churn cap.
#
# Those two sentences are the whole design. A lane that half-fails must not quietly
# unpublish four hundred people; a person who asked to be removed must be removed even
# when the lane half-failed.
#
# ZERO OUTPUT IS SAFE BY CONSTRUCTION. A run with an empty publish set writes nothing,
# deletes no churn, still executes consent deletes, and never creates or empties
# `Devs/` — so the site's `assertDevsIntegrity()` empty-corpus floor cannot be tripped by
# one bad CEREBRO morning.

#: The directory this module owns. It touches nothing else under the vault root.
CORPUS_DIR = "Devs"

#: The churn cap. Refuse the churn deletions WHOLESALE past `max(25, 25% of corpus)`,
#: keep the corpus intact, and return a loud reason the pipeline stage turns into a page.
#: Wholesale rather than "delete the first 25": a partial unpublish is a corpus that
#: agrees with neither today's run nor yesterday's.
CHURN_CAP_MIN = 25
CHURN_CAP_FRACTION = 0.25

#: `refused_reason` values. Distinct strings because the operator response differs: one
#: is "the run was bad, look at the run", the other is "the run was fine and produced
#: nobody, look at the lanes".
REFUSED_EMPTY = "empty-publish-set"
REFUSED_UNHEALTHY = "unhealthy-run"
REFUSED_CHURN_CAP = "churn-cap-exceeded"

_TIMESTAMP_LINE = re.compile(r'^generated_at: .*$', re.MULTILINE)


@dataclass(frozen=True)
class CorpusPlan:
    """What a run WOULD do to `Devs/`. Pure: no clock, no disk, no network."""

    writes: list = field(default_factory=list)
    deletes_consent: list = field(default_factory=list)
    deletes_churn: list = field(default_factory=list)
    withheld: list = field(default_factory=list)
    #: Non-empty when churn deletions were refused, and why. Never suppresses a consent
    #: deletion: those have no refusal path at all.
    refused_reason: str = ""

    @property
    def deletes(self) -> list:
        return list(self.deletes_consent) + list(self.deletes_churn)


def churn_cap(corpus_size: int) -> int:
    return max(CHURN_CAP_MIN, int(corpus_size * CHURN_CAP_FRACTION))


def plan(records, existing_logins, *, optout=None, verdicts=None, healthy=True):
    """Today's publish set against what is on disk. PURE.

    `existing_logins` is the set of `<login>` stems already in `Devs/`, exactly as the
    filenames spell them, because a deletion has to name a real file.
    """
    publish = publish_set(records, optout=optout, verdicts=verdicts)
    held = withheld(records, optout=optout, verdicts=verdicts)

    existing = list(existing_logins or [])
    optout_logins = getattr(optout, "logins", frozenset()) or frozenset()
    denied = set(getattr(verdicts, "denied", {}) or {})

    # CONSENT DELETES ARE COMPUTED FIRST AND ARE NEVER SUBJECT TO ANYTHING BELOW.
    deletes_consent = [x for x in existing
                       if slug(x) in optout_logins or slug(x) in denied]
    consent_keys = {slug(x) for x in deletes_consent}
    publish_keys = {slug(_field(r, "login", "")) for r in publish}
    churn = [x for x in existing
             if slug(x) not in publish_keys and slug(x) not in consent_keys]

    refused = ""
    if not publish:
        # Nothing to publish is not the same as "unpublish everybody". It writes nothing,
        # deletes no churn, and leaves the corpus exactly as it was.
        refused, churn = REFUSED_EMPTY, []
    elif not healthy:
        refused, churn = REFUSED_UNHEALTHY, []
    elif len(churn) > churn_cap(len(existing)):
        refused, churn = REFUSED_CHURN_CAP, []

    # THE BELT. A denied login reaching `writes` is a DEFECT, not an outcome: without the
    # sixth clause the same run would delete this person as a consent delete and re-write
    # them from this very plan. Raising is correct — the alternative is handing `apply()`
    # a page about somebody a reviewer excluded.
    leaked = sorted(k for k in publish_keys if k in denied)
    if leaked:
        raise AssertionError(
            f"denied login(s) {', '.join(leaked)} reached plan().writes. The write gate's "
            f"sixth clause exists precisely to make this unreachable; a page about a "
            f"person a reviewer excluded must never be handed to apply().")

    return CorpusPlan(writes=list(publish), deletes_consent=deletes_consent,
                      deletes_churn=list(churn), withheld=held,
                      refused_reason=refused)


def apply(corpus_plan: CorpusPlan, root) -> dict:
    """Execute a plan against `<root>/Devs/`. The only function here that touches disk.

    A note whose ONLY difference from the one on disk is `generated_at` is LEFT ALONE.
    `generated_at` means "when these facts last changed"; stamping it from the clock on
    every run would hand the public vault a full-corpus commit every morning and make its
    history mean nothing.
    """
    directory = Path(root) / CORPUS_DIR
    result = {
        "dir": str(directory),
        "written": [],
        "unchanged": [],
        "deleted": [],
        "refused_reason": corpus_plan.refused_reason,
        "withheld": len(corpus_plan.withheld),
    }

    if not corpus_plan.writes and not corpus_plan.deletes:
        # NEVER create the directory just to leave it empty: the site treats an existing
        # but empty `Devs/` as a broken clone and makes it a build-killing throw.
        return result

    if corpus_plan.writes:
        directory.mkdir(parents=True, exist_ok=True)
        _sweep_stale(directory)

    for record in corpus_plan.writes:
        login = str(_field(record, "login", ""))
        target = directory / f"{login}.md"
        text = render(_as_dict(record))
        if target.exists() and _same_facts(target.read_text(encoding="utf-8"), text):
            result["unchanged"].append(login)
            continue
        _atomic_write(target, text)
        result["written"].append(login)

    for login in corpus_plan.deletes:
        target = directory / f"{login}.md"
        try:
            target.unlink()
            result["deleted"].append(login)
        except FileNotFoundError:
            pass

    return result


def write_corpus(records, settings, *, optout=None, verdicts=None, healthy=True):
    """Resolve the root the way the roundup does, plan, and apply. Returns the result.

    `settings.dry_run` sends the whole corpus to `<vault>/_scratch/Devs/`, which is the
    only mode this epic ever runs.
    """
    root = (Path(settings.vault_path) / "_scratch") if settings.dry_run \
        else Path(settings.vault_path)
    existing = existing_logins(root)
    corpus_plan = plan(records, existing, optout=optout, verdicts=verdicts,
                       healthy=healthy)
    out = apply(corpus_plan, root)
    out["dry_run"] = bool(settings.dry_run)
    out["plan"] = {
        "writes": len(corpus_plan.writes),
        "deletes_consent": len(corpus_plan.deletes_consent),
        "deletes_churn": len(corpus_plan.deletes_churn),
        "withheld": len(corpus_plan.withheld),
        "existing": len(existing),
    }
    return corpus_plan, out


def existing_logins(root) -> list[str]:
    """The `<login>` stems already in `<root>/Devs/`, sorted. Empty when absent."""
    directory = Path(root) / CORPUS_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))


def _as_dict(record) -> dict:
    if isinstance(record, dict):
        return record
    from dataclasses import asdict, is_dataclass
    return asdict(record) if is_dataclass(record) else dict(record)


def _same_facts(old: str, new: str) -> bool:
    """Equal once `generated_at` is elided from both. See 1.6."""
    blank = 'generated_at: ""'
    return (_TIMESTAMP_LINE.sub(blank, old, count=1)
            == _TIMESTAMP_LINE.sub(blank, new, count=1))


def _sweep_stale(directory: Path) -> None:
    for stale in directory.glob(".*.md.tmp"):
        try:
            stale.unlink()
        except OSError:
            pass


def _atomic_write(target: Path, text: str) -> None:
    """Full temp file, then `os.replace`. The roundup's discipline, restated.

    `os.replace` is atomic on POSIX, so a reader (including `run.sh`'s `git add`) can
    only ever observe a complete note. A plain `write_text` killed mid-flush would leave
    a TRUNCATED note that the next run's unchanged-comparison reads as "changed" and that
    `git add -- Devs` would push to a PUBLIC repository in the meantime.
    """
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
