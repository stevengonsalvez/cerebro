"""F017 — the quality VERDICTS file: recorded human review outcomes, both directions.

This is not a one-way denylist and it is NOT the opt-out list. Opt-out is CONSENT
(F049/F050), lives in its own file, and the two must never be merged: one records what
a reviewer concluded about an account's shape, the other records what a person asked
for. Merging them would let a quality judgement read as a consent record.

Court settled Q7 gives human review TWO terminal states, so both get an artifact:

  denied:   the only path to automation state `excluded`. No arithmetic reaches it.
  cleared:  the only durable form of "flagged-then-resolved-clear by human review".

The `cleared:` half is load-bearing. Without it a real engineer whose shapes fire is
re-flagged identically on every run and withheld for ever — suppression by
non-terminating queue, which is still suppression — and the "re-run until the queue is
empty" loop can never converge. A login in BOTH sections is a load-time error: a
contradiction in a human verdict file must stop the run, not be resolved by precedence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PATH = "config/devs_denylist.yaml"

#: Every entry in EITHER section carries all five. A bare login is not a verdict.
REQUIRED_FIELDS = ("login", "verdict", "shape", "evidence", "reviewed_by", "reviewed_on")

#: Reviewers whose signature is the OWNER'S OWN, not an agent acting on their behalf.
#: The charter's success criterion 4 says the top-20 is "verified by eye", so the record
#: has to say WHOSE eye. Everything outside this set is an agent-recorded verdict: still
#: a real review with real evidence, but not yet countersigned by the person who is
#: accountable for publishing a page about a named human. Agent-recorded clearings are
#: surfaced as a warning on every sanity-gate run so the outstanding countersign cannot
#: be lost between here and the F070 launch probe.
OWNER_REVIEWERS = frozenset({"owner", "stevie", "stevengonsalvez"})


@dataclass(frozen=True)
class VerdictEntry:
    login: str
    verdict: str
    shape: str
    evidence: str
    reviewed_by: str
    reviewed_on: str


@dataclass(frozen=True)
class Verdicts:
    denied: dict[str, VerdictEntry] = field(default_factory=dict)
    cleared: dict[str, VerdictEntry] = field(default_factory=dict)

    def __contains__(self, login: str) -> bool:
        key = (login or "").strip().lower()
        return key in self.denied or key in self.cleared


EMPTY = Verdicts()


def is_owner_signed(entry) -> bool:
    """True only when a human owner, not an agent, recorded this verdict."""
    return bool(entry) and (entry.reviewed_by or "").strip().lower() in OWNER_REVIEWERS


def load(path=DEFAULT_PATH) -> Verdicts:
    """Parse and validate both sections. Raises ValueError on any malformed entry."""
    p = Path(path)
    if not p.is_file():
        return Verdicts()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping with denied:/cleared: sections")

    denied = _section(raw.get("denied"), "denied", path)
    cleared = _section(raw.get("cleared"), "cleared", path)

    both = sorted(set(denied) & set(cleared))
    if both:
        raise ValueError(
            f"{path}: {', '.join(both)} appear in BOTH denied: and cleared:. "
            "A contradiction in a human verdict file must be resolved by a human, "
            "never by precedence."
        )
    return Verdicts(denied=denied, cleared=cleared)


def _section(rows, name: str, path) -> dict[str, VerdictEntry]:
    if rows is None:
        return {}
    if not isinstance(rows, list):
        raise ValueError(f"{path}: `{name}:` must be a list of entries, got {type(rows).__name__}")

    out: dict[str, VerdictEntry] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(
                f"{path}: `{name}[{i}]` is {row!r}, not an entry. Every verdict carries "
                f"{', '.join(REQUIRED_FIELDS)} — a bare login is not a recorded decision."
            )
        missing = [f for f in REQUIRED_FIELDS
                   if not str(row.get(f) or "").strip()]
        if missing:
            raise ValueError(
                f"{path}: `{name}` entry {row.get('login') or f'#{i}'} is missing "
                f"{', '.join(missing)}. Every verdict in both sections carries all "
                f"{len(REQUIRED_FIELDS)} fields."
            )
        entry = VerdictEntry(**{f: str(row[f]).strip() for f in REQUIRED_FIELDS})
        out[entry.login.lower()] = entry
    return out
