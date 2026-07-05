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

    def close(self) -> None:
        self.db.close()


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
