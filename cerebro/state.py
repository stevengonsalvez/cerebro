from __future__ import annotations

import os
import pathlib
import sqlite3

from .models import RunStats, Signal

_ROOT = pathlib.Path(__file__).resolve().parent.parent

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
CREATE TABLE IF NOT EXISTS source_health (
  run_id TEXT, source TEXT, count INTEGER, ok INTEGER, ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_sh_source ON source_health(source);
"""


class State:
    """SQLite seen-hash store + run log. The dedup window is enforced here."""

    def __init__(self, db_path: str | None = None):
        # anchor to repo ROOT (like vault/.env/accounts.db) so cron/launchd with a different
        # CWD doesn't open a fresh empty DB and silently reset the dedup watermark.
        db_path = db_path or os.environ.get("CEREBRO_DB") or str(_ROOT / "cerebro.sqlite")
        self.db = sqlite3.connect(str(db_path))
        self.db.executescript(SCHEMA)
        # migrate older DBs: add token-usage columns if missing
        for col in ("input_tokens INTEGER", "output_tokens INTEGER", "cache_read INTEGER",
                    "cache_creation INTEGER", "cost_usd REAL", "llm_calls INTEGER"):
            try:
                self.db.execute(f"ALTER TABLE runs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass

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
            "after_dedup,after_triage,digested,dry_run,x_ok,error,"
            "input_tokens,output_tokens,cache_read,cache_creation,cost_usd,llm_calls)"
            " VALUES(?,datetime('now'),datetime('now'),?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (st.run_id, st.raw, st.after_dedup, st.after_triage, st.digested,
             int(st.dry_run), int(st.x_ok), st.error,
             st.input_tokens, st.output_tokens, st.cache_read, st.cache_creation,
             st.cost_usd, st.llm_calls),
        )
        self.db.commit()

    def log_source(self, run_id: str, source: str, count: int, ok: bool) -> None:
        self.db.execute(
            "INSERT INTO source_health(run_id,source,count,ok,ts) VALUES(?,?,?,?,datetime('now'))",
            (run_id, source, count, int(ok)),
        )
        self.db.commit()

    def source_summary(self) -> list[tuple]:
        return self.db.execute(
            "SELECT source, COUNT(*) AS runs, ROUND(AVG(count),1) AS avg, "
            "SUM(count=0 OR ok=0) AS zero_or_fail, MAX(ts) AS last_seen "
            "FROM source_health GROUP BY source ORDER BY source"
        ).fetchall()

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
