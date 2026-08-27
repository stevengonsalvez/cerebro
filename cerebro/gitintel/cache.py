from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
from typing import Any

from ..config import ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS github_responses (
  cache_key TEXT PRIMARY KEY,
  response_json TEXT NOT NULL,
  status_code INTEGER NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repo_inspections (
  full_name TEXT PRIMARY KEY,
  inspection_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_inspections (
  login TEXT PRIMARY KEY,
  inspection_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_runs (
  run_id TEXT PRIMARY KEY,
  input_query TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repo_metric_snapshots (
  full_name TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  stars INTEGER NOT NULL,
  forks INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(full_name, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_repo_metric_snapshots_lookup
  ON repo_metric_snapshots(full_name, captured_at);
CREATE TABLE IF NOT EXISTS developer_metric_snapshots (
  login TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  followers INTEGER NOT NULL,
  public_repos INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(login, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_developer_metric_snapshots_lookup
  ON developer_metric_snapshots(login, captured_at);
CREATE TABLE IF NOT EXISTS active_day_snapshots (
  login TEXT NOT NULL,
  window_days INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  active_days INTEGER NOT NULL,
  PRIMARY KEY(login, window_days, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_active_day_snapshots_lookup
  ON active_day_snapshots(login, window_days, captured_at);
CREATE TABLE IF NOT EXISTS push_window_snapshots (
  login TEXT NOT NULL,
  window_days INTEGER NOT NULL,
  captured_at TEXT NOT NULL,
  pushes INTEGER NOT NULL,
  distinct_repos INTEGER NOT NULL,
  repos_not_owned INTEGER NOT NULL DEFAULT 0,
  not_owned_basenames INTEGER NOT NULL DEFAULT 0,
  not_owned_owners INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(login, window_days, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_push_window_snapshots_lookup
  ON push_window_snapshots(login, window_days, captured_at);
"""


class GitIntelCache:
    def __init__(self, path: str | pathlib.Path | None = None, ttl_hours: int = 24):
        if str(path) == ":memory:":
            p = pathlib.Path(":memory:")
        else:
            p = pathlib.Path(path or ROOT / "cerebro-gitintel.sqlite")
        if str(p) != ":memory:" and not p.is_absolute():
            p = ROOT / p
        self.path = p
        self.ttl = dt.timedelta(hours=ttl_hours)
        self.db = sqlite3.connect(str(p))
        self.db.executescript(SCHEMA)

    def _fresh(self, fetched_at: str) -> bool:
        try:
            then = dt.datetime.fromisoformat(fetched_at)
        except ValueError:
            return False
        return dt.datetime.now() - then <= self.ttl

    def get_response(self, key: str) -> tuple[int, Any] | None:
        row = self.db.execute(
            "SELECT status_code,response_json,fetched_at FROM github_responses WHERE cache_key=?",
            (key,),
        ).fetchone()
        if not row or not self._fresh(row[2]):
            return None
        return int(row[0]), json.loads(row[1])

    def set_response(self, key: str, status_code: int, data: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO github_responses VALUES(?,?,?,?)",
            (key, json.dumps(data), int(status_code), dt.datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()

    def get_json(self, table: str, key_col: str, key: str) -> Any | None:
        row = self.db.execute(
            f"SELECT {table[:-1] if table.endswith('s') else table}_json,fetched_at FROM {table} WHERE {key_col}=?",
            (key,),
        ).fetchone()
        if not row or not self._fresh(row[1]):
            return None
        return json.loads(row[0])

    def record_repo_metrics(
        self,
        full_name: str,
        *,
        stars: int,
        forks: int = 0,
        captured_at: str | None = None,
    ) -> None:
        if not full_name:
            return
        self.db.execute(
            "INSERT OR REPLACE INTO repo_metric_snapshots VALUES(?,?,?,?)",
            (full_name.lower(), captured_at or _now_iso(), int(stars), int(forks)),
        )
        self.db.commit()

    def repo_metric_snapshots(self, full_name: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """
            SELECT captured_at,stars,forks
            FROM repo_metric_snapshots
            WHERE full_name=?
            ORDER BY captured_at ASC
            """,
            (full_name.lower(),),
        ).fetchall()
        return [
            {"captured_at": row[0], "stars": int(row[1]), "forks": int(row[2])}
            for row in rows
        ]

    def record_developer_metrics(
        self,
        login: str,
        *,
        followers: int,
        public_repos: int = 0,
        captured_at: str | None = None,
    ) -> None:
        if not login:
            return
        self.db.execute(
            "INSERT OR REPLACE INTO developer_metric_snapshots VALUES(?,?,?,?)",
            (login.lower(), captured_at or _now_iso(), int(followers), int(public_repos)),
        )
        self.db.commit()

    def developer_metric_snapshots(self, login: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """
            SELECT captured_at,followers,public_repos
            FROM developer_metric_snapshots
            WHERE login=?
            ORDER BY captured_at ASC
            """,
            (login.lower(),),
        ).fetchall()
        return [
            {
                "captured_at": row[0],
                "followers": int(row[1]),
                "public_repos": int(row[2]),
            }
            for row in rows
        ]

    # --- F057: the window-metric snapshots the devs lane writes about ITSELF ------
    #
    # THERE IS NO `record=False` PARAMETER HERE, AND THAT ABSENCE IS THE FEATURE.
    # `crackscore.py:39,44` passes `record=False` to the metric readers, so the scorer
    # never wrote the history its own growth terms read, and could never self-heal: the
    # follower and portfolio terms are structurally 0 without a snapshot >=7 days old,
    # which put admission arithmetically out of reach against its own threshold. The way
    # a pipeline ends up with no history is a flag whose default was wrong at one call
    # site. A caller that must not persist opens a cache on `:memory:`.
    #
    # TWO TABLES, NOT ONE WIDE ONE, because they have different jobs and therefore
    # different retention: every row of `active_day_snapshots` is an F024 growth input
    # and nothing else, so the retention constant that protects the growth horizon has
    # exactly one table to protect; `push_window_snapshots` is the last-known-good record
    # the F058 degradation report dates itself from.

    def record_window_metrics(self, login: str, window_days: int, metrics,
                              captured_at: str | None = None) -> int:
        """One login/window's push facts into both snapshot tables. Returns rows written.

        `metrics` is duck-typed on `gharchive.WindowMetrics` rather than imported: this
        module is infrastructure under the lane, and importing the lane back into it
        would make the cache depend on the thing that caches through it.

        `captured_at` is passed by the caller for the WHOLE run so one run produces one
        instant across the whole pool. A per-login `_now_iso()` would put a 2,568-login
        run's rows on either side of a second boundary and make "how many logins did this
        run snapshot" unanswerable by `count(distinct captured_at)`.
        """
        if not login:
            return 0
        stamp = captured_at or _now_iso()
        key = str(login).lower()
        window = int(window_days)
        self.db.execute(
            "INSERT OR REPLACE INTO active_day_snapshots VALUES(?,?,?,?)",
            (key, window, stamp, _as_int(getattr(metrics, "active_days", 0))),
        )
        self.db.execute(
            "INSERT OR REPLACE INTO push_window_snapshots VALUES(?,?,?,?,?,?,?,?)",
            (key, window, stamp,
             _as_int(getattr(metrics, "pushes", 0)),
             _as_int(getattr(metrics, "distinct_repos", 0)),
             _as_int(getattr(metrics, "repos_not_owned", 0)),
             _as_int(getattr(metrics, "not_owned_basenames", 0)),
             _as_int(getattr(metrics, "not_owned_owners", 0))),
        )
        self.db.commit()
        return 2

    def active_day_snapshots(self, login: str, window_days: int) -> list[dict[str, Any]]:
        """Every active-days row for one login/window, oldest first. F024's only input."""
        rows = self.db.execute(
            """
            SELECT captured_at,active_days
            FROM active_day_snapshots
            WHERE login=? AND window_days=?
            ORDER BY captured_at ASC
            """,
            (str(login).lower(), int(window_days)),
        ).fetchall()
        return [{"captured_at": r[0], "active_days": int(r[1])} for r in rows]

    def push_window_snapshots(self, login: str, window_days: int) -> list[dict[str, Any]]:
        """Every push-window row for one login/window, oldest first."""
        rows = self.db.execute(
            """
            SELECT captured_at,pushes,distinct_repos,repos_not_owned,
                   not_owned_basenames,not_owned_owners
            FROM push_window_snapshots
            WHERE login=? AND window_days=?
            ORDER BY captured_at ASC
            """,
            (str(login).lower(), int(window_days)),
        ).fetchall()
        return [
            {"captured_at": r[0], "pushes": int(r[1]), "distinct_repos": int(r[2]),
             "repos_not_owned": int(r[3]), "not_owned_basenames": int(r[4]),
             "not_owned_owners": int(r[5])}
            for r in rows
        ]

    def last_snapshot_at(self) -> str | None:
        """The newest `captured_at` in `push_window_snapshots`, or None when there is none.

        THE OPERATOR'S AS-OF, and the reason F058's degraded page is worth reading: it is
        how somebody at 07:05 tells "ClickHouse died this morning" from "this stage has
        been dead for nine days". `None` means no run has ever recorded history, which is
        a different and louder statement than an old date.
        """
        row = self.db.execute(
            "SELECT max(captured_at) FROM push_window_snapshots").fetchone()
        return row[0] if row and row[0] else None

    def close(self) -> None:
        self.db.close()


def _as_int(value) -> int:
    """Total by construction: a missing or malformed count is 0, never a raise.

    A snapshot write happens inside the run's free lane, before admission. It must
    never be the thing that takes a run down."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
