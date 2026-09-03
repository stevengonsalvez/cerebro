"""F069 — the drift alarm that tells "the endpoint is down" apart from "the query moved".

WHY THIS EXISTS RATHER THAN A COMMENT SAYING "WATCH FOR SCHEMA CHANGES". The feed IS
proven to drift structurally: registry s1 measured `github_events`' PushEvent share moving
from 96.2% to 68.5%, and this whole lane reads four columns of one table on a free,
no-SLA, community-run endpoint. When that table changes underneath the pool query, today's
failure arrives at an operator as `UNREACHABLE`, which sends them to read a status page
about a service that is answering perfectly.

WHAT IS CHECKED, AND WHAT IS DELIBERATELY NOT.

    checked      the four columns `POOL_SQL` actually reads, their base types, the
                 `PushEvent` member of the `event_type` enum, and whether the feed is
                 still moving.
    NOT checked  the other 50 columns. `github_events` had 54 on 2026-08-27 and upstream
                 adds and retypes columns this lane never reads. An alarm that fires on
                 those is an alarm that gets muted, and a muted alarm is worse than none.

EVERY BOUND HERE IS AN ORDER OF MAGNITUDE OF SLACK AROUND A LIVE MEASUREMENT, taken
2026-08-27: newest PushEvent `2026-08-27 02:59:57` (about 6 h of ingest lag), 6,450,031
PushEvents in 72 h. The assertions are `>= now - 48h` and `> 100,000`, i.e. eight times
the observed lag and one sixty-fourth of the observed volume. They are re-derived, not
nudged, if the feed's shape moves.

NO NUMBER HERE ORDERS ANYBODY. This module never sees a login.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import gharchive

#: The four columns `POOL_SQL` reads, with the BASE type each must still carry. Measured
#: live: `actor_login` and `repo_name` are `LowCardinality(String)`, which unwraps to
#: `String` — the wrapper is an encoding decision upstream may change freely, so it is
#: tolerated, while `String` -> `UInt64` is not, because that breaks the IN-list.
EXPECTED_COLUMNS = (
    ("actor_login", "String"),
    ("repo_name", "String"),
    ("created_at", "DateTime"),
    ("event_type", "Enum8"),
)

#: The enum member the pool query filters on. Losing it would silently return zero rows
#: for every login in the pool, which reads downstream as "2,568 people stopped shipping".
REQUIRED_EVENT_TYPE = "PushEvent"

#: Feed liveness bounds. See the module docstring for the live measurements they bracket.
MAX_FEED_LAG_HOURS = 48
MIN_PUSHES_72H = 100_000

DESCRIBE_SQL = "DESCRIBE TABLE github_events FORMAT TSVWithNames"

LIVENESS_SQL = (
    "SELECT max(created_at) AS newest_at, count() AS pushes_72h\n"
    "FROM github_events\n"
    "WHERE event_type = 'PushEvent' AND created_at >= now() - INTERVAL 72 HOUR\n"
    "FORMAT TSVWithNames"
)

_WRAPPERS = ("LowCardinality", "Nullable")


@dataclass(frozen=True)
class Drift:
    """One thing that moved, named so the page text can say WHICH column.

    `subject` is the column or property; `detail` is what was expected against what is
    there. A drift report that says "the schema changed" is not actionable at 07:05.
    """

    subject: str
    detail: str

    def to_dict(self) -> dict:
        return {"subject": self.subject, "detail": self.detail}


@dataclass
class ContractReport:
    """The whole answer, as data. The CLI turns it into an exit code and a page."""

    ok: bool = False
    columns_checked: tuple[str, ...] = ()
    enum_member: str = ""
    newest_at: str = ""
    pushes_72h: int = 0
    liveness_checked: bool = True
    drift: list = field(default_factory=list)
    queries: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "columns_checked": list(self.columns_checked),
            "enum_member": self.enum_member,
            "newest_at": self.newest_at,
            "pushes_72h": self.pushes_72h,
            "liveness_checked": self.liveness_checked,
            "drift": [d.to_dict() for d in self.drift],
            "queries": self.queries,
        }


def base_type(declared: str) -> str:
    """`LowCardinality(String)` -> `String`, `Enum8(...)` -> `Enum8`. Pure.

    Wrappers are an upstream encoding decision and are unwrapped rather than asserted;
    the parameterised head of a parametric type is kept, because `Enum8(a, b)` and
    `Enum8(a)` differ in a way this lane cares about and the enum check reads the raw
    declaration for exactly that.
    """
    text = (declared or "").strip()
    changed = True
    while changed:
        changed = False
        for wrapper in _WRAPPERS:
            prefix = wrapper + "("
            if text.startswith(prefix) and text.endswith(")"):
                text = text[len(prefix):-1].strip()
                changed = True
    head = text.split("(", 1)[0].strip()
    return head or text


def parse_describe(describe_tsv: str) -> dict[str, str]:
    """`DESCRIBE TABLE ... FORMAT TSVWithNames` -> `{column: declared_type}`. Total.

    A body that is not a describe at all returns `{}`, which every caller reads as "every
    expected column is missing" — fail loud, never fail open.
    """
    rows = (describe_tsv or "").splitlines()
    if not rows:
        return {}
    header = rows[0].split("\t")
    try:
        name_idx = header.index("name")
        type_idx = header.index("type")
    except ValueError:
        return {}
    out: dict[str, str] = {}
    for line in rows[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) <= max(name_idx, type_idx):
            continue
        out[cells[name_idx].strip()] = unescape_tsv(cells[type_idx].strip())
    return out


def unescape_tsv(cell: str) -> str:
    """Undo ClickHouse's TSV escaping. `Enum8(\\'PushEvent\\' = 12)` -> `Enum8('PushEvent' = 12)`.

    NOT COSMETIC. The enum check looks for the literal `'PushEvent'`, and the raw cell
    carries `\\'PushEvent\\'`; without this the check fires on every healthy run, which is
    precisely how an alarm gets muted before it ever catches anything.
    """
    out: list[str] = []
    escaped = False
    for ch in cell or "":
        if escaped:
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(ch, ch))
            escaped = False
        elif ch == "\\":
            escaped = True
        else:
            out.append(ch)
    if escaped:
        out.append("\\")
    return "".join(out)


def check_columns(describe_tsv: str) -> list[Drift]:
    """Every way the four columns this lane reads can have moved. Pure."""
    declared = parse_describe(describe_tsv)
    drift: list[Drift] = []
    if not declared:
        return [Drift("github_events", "DESCRIBE returned nothing this lane could parse")]
    for name, expected in EXPECTED_COLUMNS:
        actual = declared.get(name)
        if actual is None:
            drift.append(Drift(name, f"column is gone; POOL_SQL reads it as {expected}"))
            continue
        got = base_type(actual)
        if got != expected:
            drift.append(Drift(
                name, f"base type moved {expected} -> {got} (declared {actual!r})"))
    event_type = declared.get("event_type")
    if event_type is not None and f"'{REQUIRED_EVENT_TYPE}'" not in event_type:
        drift.append(Drift(
            "event_type",
            f"the enum no longer carries {REQUIRED_EVENT_TYPE!r}; the pool query would "
            f"return zero rows for every login"))
    return drift


def check_liveness(pushes_72h, newest_at: str, *, now=None) -> list[Drift]:
    """Is the feed still moving? Pure arithmetic over two numbers from one aggregate.

    A STALLED FEED IS NOT AN OUTAGE AND NOT DRIFT, and it is the failure this lane would
    otherwise publish as fact: every window count would fall toward zero and 2,568 real
    people would appear to have stopped working.
    """
    now_dt = now() if callable(now) else (now or datetime.now(timezone.utc))
    drift: list[Drift] = []
    parsed = parse_clickhouse_datetime(newest_at)
    if parsed is None:
        drift.append(Drift("newest_at", f"unparseable newest PushEvent {newest_at!r}"))
    else:
        lag = (now_dt - parsed).total_seconds() / 3600.0
        if lag > MAX_FEED_LAG_HOURS:
            drift.append(Drift(
                "newest_at",
                f"newest PushEvent is {lag:.1f}h old, past the {MAX_FEED_LAG_HOURS}h "
                f"bound; the feed has stalled"))
    try:
        count = int(pushes_72h)
    except (TypeError, ValueError):
        count = 0
    if count <= MIN_PUSHES_72H:
        drift.append(Drift(
            "pushes_72h",
            f"{count} PushEvents in 72h, at or under the {MIN_PUSHES_72H} floor "
            f"(6,450,031 measured 2026-08-27)"))
    return drift


def parse_clickhouse_datetime(value: str):
    """`2026-08-27 02:59:57` -> aware UTC datetime, or None. Total."""
    text = (value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text):
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_liveness(body: str) -> tuple[str, int]:
    """One TSVWithNames row -> `(newest_at, pushes_72h)`. Total; `("", 0)` on nonsense."""
    rows = [r for r in (body or "").splitlines() if r.strip()]
    if len(rows) < 2:
        return "", 0
    header = rows[0].split("\t")
    cells = rows[1].split("\t")
    try:
        newest = cells[header.index("newest_at")].strip()
        count = cells[header.index("pushes_72h")].strip()
    except (ValueError, IndexError):
        return "", 0
    try:
        return newest, int(count)
    except ValueError:
        return newest, 0


def _clock(now):
    """`now` may be a datetime or a callable; the retry ladder wants a callable."""
    if now is None:
        return lambda: datetime.now(timezone.utc)
    if callable(now):
        return now
    return lambda: now


def run_check(transport=None, *, now=None, sleep=None, offline_describe=None
              ) -> ContractReport:
    """The whole check. TWO cheap queries, or zero when `offline_describe` is given.

    `DESCRIBE TABLE` scans 0 rows (measured: 0.08 s, registry s5) and the liveness
    aggregate reads one 72-hour partition. That is a FOURTH ClickHouse query per day
    beside the run's three, recorded as an amendment to F056's measured budget rather than
    absorbed silently.

    The transport goes through `gharchive._post_with_retries`, so this check has exactly
    the same retry, quota and drift semantics as the pool query it is guarding — one
    retry policy in the lane, not two that disagree the first time somebody edits one.
    """
    report = ContractReport()
    if offline_describe is not None:
        report.liveness_checked = False
        report.drift = check_columns(offline_describe)
        report.columns_checked = tuple(name for name, _ in EXPECTED_COLUMNS)
        report.enum_member = REQUIRED_EVENT_TYPE
        report.ok = not report.drift
        return report

    post = transport or gharchive._http_post
    clock = _clock(now)
    describe = gharchive._post_with_retries(
        post, DESCRIBE_SQL, sleep=sleep or time.sleep, now=clock)
    report.queries += 1
    report.drift = check_columns(describe)
    report.columns_checked = tuple(name for name, _ in EXPECTED_COLUMNS)
    report.enum_member = REQUIRED_EVENT_TYPE

    body = gharchive._post_with_retries(
        post, LIVENESS_SQL, sleep=sleep or time.sleep, now=clock)
    report.queries += 1
    report.newest_at, report.pushes_72h = parse_liveness(body)
    report.drift = list(report.drift) + check_liveness(
        report.pushes_72h, report.newest_at, now=clock)
    report.ok = not report.drift
    return report
