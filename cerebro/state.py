from __future__ import annotations

import sqlite3

from .models import RunStats, Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
  url_hash   TEXT PRIMARY KEY,
  simhash    INTEGER,
  url        TEXT,
  title      TEXT,
  source     TEXT,
  category   TEXT,
  score      REAL,
  first_seen TEXT NOT NULL,
  last_seen  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_first ON seen(first_seen);
CREATE TABLE IF NOT EXISTS runs (
  run_id      TEXT PRIMARY KEY,
  started_at  TEXT, finished_at TEXT,
  raw_count   INTEGER, after_dedup INTEGER, after_triage INTEGER, digested INTEGER,
  dry_run     INTEGER, x_ok INTEGER, error TEXT
);
"""


class State:
    """SQLite seen-hash store + run log. The dedup window is enforced here."""

    def __init__(self, db_path: str = "cerebro.sqlite"):
        self.db = sqlite3.connect(str(db_path))
        self.db.executescript(SCHEMA)

    def seen_recent(self, url_hash: str, days: int) -> bool:
        cur = self.db.execute(
            "SELECT 1 FROM seen WHERE url_hash=? AND first_seen >= date('now', ?)",
            (url_hash, f"-{days} days"),
        )
        return cur.fetchone() is not None

    def recent_simhashes(self, days: int) -> list[int]:
        cur = self.db.execute(
            "SELECT simhash FROM seen WHERE first_seen >= date('now', ?)",
            (f"-{days} days",),
        )
        return [r[0] for r in cur.fetchall() if r[0] is not None]

    def mark(self, s: Signal) -> None:
        self.db.execute(
            "INSERT INTO seen(url_hash,simhash,url,title,source,category,score,first_seen,last_seen)"
            " VALUES(?,?,?,?,?,?,?,date('now'),date('now'))"
            " ON CONFLICT(url_hash) DO UPDATE SET last_seen=date('now')",
            (s.url_hash, s.simhash, s.url, s.title, s.source, s.category, s.score),
        )
        self.db.commit()

    def log_run(self, st: RunStats) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO runs(run_id,started_at,finished_at,raw_count,"
            "after_dedup,after_triage,digested,dry_run,x_ok,error)"
            " VALUES(?,datetime('now'),datetime('now'),?,?,?,?,?,?,?)",
            (st.run_id, st.raw, st.after_dedup, st.after_triage, st.digested,
             int(st.dry_run), int(st.x_ok), st.error),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":  # ponytail: smallest runnable check for the dedup path
    st = State(":memory:")
    sig = Signal(url="https://x.com/a", title="t", source="x", url_hash="h1", simhash=42)
    assert not st.seen_recent("h1", 14)
    st.mark(sig)
    assert st.seen_recent("h1", 14)
    assert 42 in st.recent_simhashes(14)
    assert not st.seen_recent("nope", 14)
    print("state self-check OK")
