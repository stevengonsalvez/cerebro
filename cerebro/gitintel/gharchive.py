"""F006/F018/F019/F022 — GH Archive enrichment over an anchored candidate pool.

ENRICHMENT, NEVER DISCOVERY. The charter's central design constraint is empirical:
ranking GH Archive by event volume is INVERTED, not merely noisy (`github-actions[bot]`
634k pushes/7d; a volume leaderboard puts mass-repo spam ~30x above Simon Willison).
This module therefore takes a login list that some other lane already anchored and
returns facts about those logins. It never enumerates, never ranks, never sorts.

ONE SCAN PER WINDOW, THREE PER RUN, EVER. `play.clickhouse.com` enforces a SHARED
hourly 300-billion-row read quota across all anonymous users. A self-joined two-scan
version of the concentration query exhausted it on 2026-08-26 and the endpoint then
refused every pool query for the rest of the hour. The two-level GROUP BY below gets
actor aggregates, the per-basename maximum AND the per-week push series from a single
pass; `uniqExactState`/`uniqExactMerge` carries the distinct-day set across the levels
and `sumMapState`/`sumMapMerge` carries the week histogram the same way. Query count is
a correctness property here, not an optimisation, and it is asserted by test.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

ENDPOINT = "https://play.clickhouse.com/?user=play"
WINDOWS = (7, 30, 90)

#: 13 weeks ~= 91 days: the 90d scan's weekly histogram, F035's sparkline series.
WEEK_SLOTS = 13

#: Quota retries sleep until the reset the error body announces, plus this jitter.
#: A retry measured at 21:11:00 against a 21:11:08 reset was still blocked; one at
#: 21:11:46 succeeded.
QUOTA_JITTER_S = 45
#: At most two sleep-until-reset cycles (~2h worst case). Exhausting this is the
#: epic's kill criterion 6, not a transient.
QUOTA_BUDGET = 2
#: 5xx and transport errors are not quota-shaped, so they keep a short ladder.
TRANSPORT_LADDER_S = (30, 60, 120)

_QUOTA_RESET_RE = re.compile(r"Interval will end at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

POOL_SQL = """SELECT actor_login,
  sum(n_pushes)                                    AS pushes,
  sum(n_repos)                                     AS distinct_repos,
  uniqExactMerge(days_state)                       AS active_days,
  sum(n_not_owned)                                 AS repos_not_owned,
  countIf(n_not_owned > 0)                         AS not_owned_basenames,
  max(n_repos)                                     AS max_basename_group,
  sumMapMerge(weeks_state)                         AS weeks_map
FROM (
  SELECT actor_login,
    lower(splitByChar('/', repo_name)[2])          AS base,
    count()                                        AS n_pushes,
    uniqExact(repo_name)                           AS n_repos,
    uniqExactIf(repo_name,
      lower(splitByChar('/', repo_name)[1]) != lower(actor_login)) AS n_not_owned,
    uniqExactState(toDate(created_at))             AS days_state,
    sumMapState([toUInt16(intDiv(dateDiff('day', toDate(created_at), today()), 7))],
                [toUInt64(1)])                     AS weeks_state
  FROM github_events
  WHERE created_at >= now() - INTERVAL {window} DAY
    AND event_type = 'PushEvent'
    AND actor_login IN ({logins})
  GROUP BY actor_login, base
)
GROUP BY actor_login
FORMAT TSVWithNames
"""


class GHArchiveUnavailable(RuntimeError):
    """The endpoint could not be reached within the retry budget.

    Raised after QUOTA_BUDGET waited-out quota windows (~2h) or an exhausted
    transport ladder. The caller degrades loudly with a non-zero exit; it never
    produces a partial pool silently.
    """


@dataclass(frozen=True)
class WindowMetrics:
    """One login's push facts over one window. Every field is a count, never a score."""

    window_days: int
    pushes: int = 0
    distinct_repos: int = 0
    active_days: int = 0
    repos_not_owned: int = 0
    not_owned_basenames: int = 0
    max_basename_group: int = 0
    #: 13 slots, oldest -> newest. Populated from the 90d window only; the 7d/30d
    #: rows carry zeros and nothing reads them.
    pushes_per_week: tuple[int, ...] = (0,) * WEEK_SLOTS


def quote_login(login: str) -> str:
    """SQL-escape one login into a single-quoted literal.

    GitHub logins cannot contain a quote today, but the pool is assembled from
    text mined out of arbitrary vault notes, so the escaping is real, not decorative.
    """
    return "'" + str(login).replace("\\", "\\\\").replace("'", "\\'") + "'"


def render_sql(logins, window_days: int) -> str:
    """The exact bytes POSTed for one window. Public so validation runs them verbatim."""
    in_list = ", ".join(quote_login(x) for x in logins)
    return POOL_SQL.replace("{window}", str(int(window_days))).replace("{logins}", in_list)


def densify_weeks(weeks_map: str) -> tuple[int, ...]:
    """`([k...],[v...])` -> a dense 13-tuple, oldest -> newest.

    The map is SPARSE (a live t3dotgg row was missing keys 8, 11 and 12) and its keys
    count BACKWARDS: key 0 is the current partial week, key 12 the oldest. Densify with
    zero-fill, drop keys past the window, then reverse — a sparkline reads left to right
    in time. Pure arithmetic, in the client, never in SQL.
    """
    slots = [0] * WEEK_SLOTS
    if not weeks_map:
        return tuple(slots)
    keys_s, _, vals_s = weeks_map.partition("],[")
    keys = _ints(keys_s)
    vals = _ints(vals_s)
    for k, v in zip(keys, vals):
        if 0 <= k < WEEK_SLOTS:
            slots[k] = v
    slots.reverse()
    return tuple(slots)


def _ints(chunk: str) -> list[int]:
    out = []
    for tok in re.findall(r"-?\d+", chunk or ""):
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return out


def pool_metrics(logins, *, windows=WINDOWS, transport=None, sleep=None, now=None):
    """{login: {window_days: WindowMetrics}} for every login given, in len(windows) POSTs.

    A login absent from a result is ZERO ACTIVITY, not an error and never a KeyError:
    78 of the real 175-owner pool is exactly this case, and suppressing them would
    encode an attribution limitation as a fact about a person.
    """
    logins = list(dict.fromkeys(logins))
    transport = transport or _http_post
    sleep = sleep or time.sleep
    now = now or (lambda: datetime.now(timezone.utc))

    out: dict[str, dict[int, WindowMetrics]] = {
        login: {w: WindowMetrics(window_days=w) for w in windows} for login in logins
    }
    if not logins:
        return out

    for window in windows:
        sql = render_sql(logins, window)
        body = _post_with_retries(transport, sql, sleep=sleep, now=now)
        for login, m in _parse_tsv(body, window).items():
            key = _match_login(out, login)
            if key is not None:
                out[key][window] = m
    return out


def _match_login(out: dict, login: str) -> str | None:
    if login in out:
        return login
    low = login.lower()
    for k in out:
        if k.lower() == low:
            return k
    return None


def _parse_tsv(body: str, window: int) -> dict[str, WindowMetrics]:
    rows = (body or "").splitlines()
    if not rows:
        return {}
    header = rows[0].split("\t")
    try:
        idx = {name: header.index(name) for name in (
            "actor_login", "pushes", "distinct_repos", "active_days", "repos_not_owned",
            "not_owned_basenames", "max_basename_group", "weeks_map")}
    except ValueError:  # a column vanished -> the contract moved, not a transient
        raise GHArchiveUnavailable(f"unexpected result header: {header!r}") from None

    out: dict[str, WindowMetrics] = {}
    for line in rows[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) < len(header):
            continue
        login = cells[idx["actor_login"]]
        active = _int(cells[idx["active_days"]])
        if active > window:
            # F022 carry-in: a real active_days_30d == 31 was recorded. The window is
            # a hard bound by construction, so a larger value is a boundary artifact.
            log.warning("gharchive: clamping %s active_days %d -> %d (%dd window)",
                        login, active, window, window)
            active = window
        out[login] = WindowMetrics(
            window_days=window,
            pushes=_int(cells[idx["pushes"]]),
            distinct_repos=_int(cells[idx["distinct_repos"]]),
            active_days=active,
            repos_not_owned=_int(cells[idx["repos_not_owned"]]),
            not_owned_basenames=_int(cells[idx["not_owned_basenames"]]),
            max_basename_group=_int(cells[idx["max_basename_group"]]),
            pushes_per_week=(densify_weeks(cells[idx["weeks_map"]])
                             if window == 90 else (0,) * WEEK_SLOTS),
        )
    return out


def _int(v) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _post_with_retries(transport, sql: str, *, sleep, now) -> str:
    """POST once, then retry per the failure's SHAPE.

    Quota is not congestion: the error body names the instant the shared hourly window
    resets, so the client WAITS FOR IT. A fixed 60/120/240s ladder is ~7 minutes of
    patience against a window that can have 59 minutes left; launched at :15 past it
    dies 38 minutes before a reset it could simply have waited for, and reports a fully
    recoverable condition as GHArchiveUnavailable.
    """
    quota_waits = 0
    transport_attempt = 0
    while True:
        try:
            body = transport(sql)
        except Exception as exc:  # noqa: BLE001 — transport-shaped, short ladder
            if transport_attempt >= len(TRANSPORT_LADDER_S):
                raise GHArchiveUnavailable(f"transport failed: {exc}") from exc
            sleep(TRANSPORT_LADDER_S[transport_attempt])
            transport_attempt += 1
            continue

        if not _is_error(body):
            return body

        if _is_quota(body):
            if quota_waits >= QUOTA_BUDGET:
                raise GHArchiveUnavailable(
                    f"clickhouse quota exhausted across {QUOTA_BUDGET} windows: "
                    f"{body[:300]}")
            wait = _seconds_until_reset(body, now())
            log.warning("gharchive: quota exceeded, sleeping %.0fs until the announced reset",
                        wait)
            sleep(wait)
            quota_waits += 1
            continue

        if transport_attempt >= len(TRANSPORT_LADDER_S):
            raise GHArchiveUnavailable(f"clickhouse error: {body[:300]}")
        sleep(TRANSPORT_LADDER_S[transport_attempt])
        transport_attempt += 1


def _is_error(body: str) -> bool:
    head = (body or "")[:400]
    return "DB::Exception" in head or head.strip().startswith("Code:")


def _is_quota(body: str) -> bool:
    return "Quota for user" in (body or "")[:600] or "QUOTA_EXCEEDED" in (body or "")[:600]


def _seconds_until_reset(body: str, now_dt: datetime) -> float:
    """Seconds to sleep: to the announced reset + jitter, else to the next hour + jitter."""
    m = _QUOTA_RESET_RE.search(body or "")
    if m:
        try:
            reset = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc)
        except ValueError:
            reset = None
    else:
        reset = None
    if reset is None:
        reset = (now_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    delta = (reset - now_dt).total_seconds() + QUOTA_JITTER_S
    return max(float(QUOTA_JITTER_S), delta)


def _http_post(sql: str) -> str:
    req = urllib.request.Request(
        ENDPOINT, data=sql.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8",
                 "User-Agent": "cerebro-devs/e01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # ClickHouse returns errors as a 4xx/5xx body
        return e.read().decode("utf-8", "replace")
