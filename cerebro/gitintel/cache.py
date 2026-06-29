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

    def close(self) -> None:
        self.db.close()
