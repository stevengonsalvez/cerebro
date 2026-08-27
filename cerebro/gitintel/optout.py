"""F049 — CONSENT. The people who asked not to be in /cerebro/devs, and the gate.

THIS MODULE IS NOT `denylist.py` AND IT NEVER IMPORTS IT. `denylist.py` records what a
REVIEWER CONCLUDED about an account's shape; this records what a PERSON ASKED FOR. They
share no file, no dataclass and no loader, and `tests/test_optout.py` asserts the
absence of an import in both directions. Merging them would let a quality judgement read
as a consent record, and would put a removal request into a file whose every entry
demands `evidence:` and `reviewed_by:`.

IT FAILS CLOSED, AND THAT IS THE WHOLE POINT OF THE MODULE.

    file absent      -> EMPTY. Nobody has opted out. This is the normal day-one state.
    file unparseable -> ValueError. THE RUN STOPS.
    entry has no login -> ValueError. THE RUN STOPS.
    entry carries verdict/shape/evidence/reviewed_by -> ValueError, naming the OTHER file.

The middle two are the reason this is not three lines of `yaml.safe_load(...) or {}`.
Treating a corrupt consent file as "nobody opted out" publishes a person who asked to be
removed, silently, on the one path this feature exists to make impossible. A stopped run
is a paged operator; a swallowed parse error is a published human.

WHERE THE GATE IS APPLIED (two independent places inside CEREBRO, plus the site's own):

    crackscan.fetch()  candidate list   ->  no `crackscan/considered` Signal is emitted
    devs lane          after assemble   ->  never in the .sql bytes, the run json, or a
                                            REST call
    the site (F050, e05)                ->  a third layer, in the other repo

There is no ordering trick and no ranking here. This module answers one question about
one login: did this person ask to be left out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PATH = "config/devs_optout.yaml"

#: The only key an entry MUST carry. A request needs no evidence.
REQUIRED_FIELD = "login"

#: The optional ones. Recorded for the operator, read by nothing that publishes.
OPTIONAL_FIELDS = ("requested_on", "note")

#: Fields that belong to `config/devs_denylist.yaml` and are REJECTED here. An entry
#: shaped like a review conclusion in the consent file means somebody edited the wrong
#: file, and the error message says which one to use. Silently accepting it would record
#: a quality judgement as a consent record.
VERDICT_FIELDS = ("verdict", "shape", "evidence", "reviewed_by", "reviewed_on")


def slug(login: str) -> str:
    """The identity key: lowercased, `@`-stripped, whitespace-stripped login.

    The same rule as `pool.slug`, and it is re-stated rather than imported for the same
    reason `pool.slug` re-states `CrackedDev.slug`: a consent gate that took a
    dependency on the pool could not be applied BEFORE the pool exists, which is exactly
    where `crackscan.fetch()` needs it. `tests/test_optout.py` pins the two functions to
    the same answer on the same inputs so they cannot drift.
    """
    return (login or "").strip().lstrip("@").lower()


@dataclass(frozen=True)
class OptOut:
    """Every removal request, keyed by slug. No verdict, no shape, no evidence."""

    logins: frozenset[str] = frozenset()
    #: slug -> the `requested_on` day the file recorded, for the operator's audit trail.
    #: Never published, never rendered, never a fact about a person on a page.
    requested_on: dict[str, str] = field(default_factory=dict)

    def __contains__(self, login: str) -> bool:
        return slug(login) in self.logins

    def __bool__(self) -> bool:
        return bool(self.logins)

    def __len__(self) -> int:
        return len(self.logins)


EMPTY = OptOut()


def filter_logins(logins, optout: OptOut) -> list[str]:
    """Every login that did NOT opt out, order preserved."""
    return [x for x in logins if slug(x) not in optout.logins]


def partition(items, key=None, *, optout: OptOut):
    """`(kept, removed)` over anything, given a way to read the login off it.

    Returns two lists rather than filtering in place so a caller can COUNT what the gate
    removed and put it in the census. A gate whose effect is invisible in the artifact is
    indistinguishable from a gate that never ran.
    """
    read = key or (lambda x: x)
    kept, removed = [], []
    for item in items:
        (removed if slug(read(item)) in optout.logins else kept).append(item)
    return kept, removed


def load(path=DEFAULT_PATH) -> OptOut:
    """Parse the consent file. Missing is EMPTY; malformed RAISES. Never both."""
    p = Path(path)
    if not p.is_file():
        return EMPTY

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(
            f"{path}: the opt-out file exists and could not be read ({exc}). This STOPS "
            f"the run on purpose: treating an unreadable consent file as 'nobody opted "
            f"out' would publish a person who asked to be removed."
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: expected a mapping with a `logins:` list, got "
            f"{type(raw).__name__}."
        )

    rows = raw.get("logins")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError(
            f"{path}: `logins:` must be a list of entries, got {type(rows).__name__}."
        )

    logins: set[str] = set()
    requested: dict[str, str] = {}
    for i, row in enumerate(rows):
        if isinstance(row, str):
            raise ValueError(
                f"{path}: `logins[{i}]` is the bare string {row!r}. Every entry is a "
                f"mapping with a `login:` key (plus optional "
                f"{', '.join(OPTIONAL_FIELDS)})."
            )
        if not isinstance(row, dict):
            raise ValueError(
                f"{path}: `logins[{i}]` is {row!r}, not an entry with a `login:` key."
            )
        strays = [f for f in VERDICT_FIELDS if f in row]
        if strays:
            raise ValueError(
                f"{path}: `logins[{i}]` carries {', '.join(strays)} — those belong to "
                f"config/devs_denylist.yaml, which records a REVIEWER'S CONCLUSION. "
                f"This file records what a PERSON ASKED FOR and takes no evidence. The "
                f"two files are deliberately separate; put the entry in the right one."
            )
        key = slug(str(row.get(REQUIRED_FIELD) or ""))
        if not key:
            raise ValueError(
                f"{path}: `logins[{i}]` has no `login:`. An entry that names nobody "
                f"removes nobody, and silently skipping it would leave a person who "
                f"asked to be removed published."
            )
        logins.add(key)
        when = str(row.get("requested_on") or "").strip()
        if when:
            requested[key] = when

    return OptOut(logins=frozenset(logins), requested_on=requested)
