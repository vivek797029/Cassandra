"""ARGUS ingestion — RawEventSink (Task 42).

Lands normalized events into `raw_events` with (source, source_id) dedup.
Backend follows the same rule as the copilot store: PostgreSQL when
DATABASE_URL is set (schema from db/postgres/001_init.sql), SQLite otherwise
(mirror DDL below), selected via services.copilot.config.

Normalized event dict (the ingestion contract; mirrors raw_events columns):
  {source, source_id, event_type, actors{a1,a2,...}, h3_cell|None,
   occurred_at (epoch float), magnitude|None, confidence|None, payload{...}}
"""
from __future__ import annotations
import json, os, sqlite3, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.copilot.config import get_settings

SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS raw_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_id TEXT,
  event_type TEXT,
  actors TEXT,
  h3_cell TEXT,
  occurred_at REAL,
  magnitude REAL,
  confidence REAL,
  payload TEXT NOT NULL,
  ingested_at REAL,
  UNIQUE(source, source_id));
CREATE INDEX IF NOT EXISTS idx_raw_events_time ON raw_events(occurred_at);
"""

PG_INSERT = (
    "INSERT INTO raw_events (source, source_id, event_type, actors, h3_cell, "
    "occurred_at, magnitude, confidence, payload) "
    "VALUES (%s, %s, %s, %s, %s, to_timestamp(%s), %s, %s, %s) "
    "ON CONFLICT (source, source_id) DO NOTHING")


class RawEventSink:
    def __init__(self, sqlite_path: str | None = None):
        s = get_settings()
        self.backend = s.backend
        if self.backend == "postgres":
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(s.database_url, autocommit=True,
                                        row_factory=dict_row)
        else:
            path = sqlite_path or os.path.join(os.path.dirname(s.db), "ingest.db")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.executescript(SQLITE_DDL)
            self.conn.commit()

    # ------------------------------------------------------------------ write
    def insert_many(self, events: list[dict]) -> dict:
        inserted = 0
        if self.backend == "postgres":
            from psycopg.types.json import Jsonb
            with self.conn.cursor() as cur:
                for e in events:
                    cur.execute(PG_INSERT, (
                        e["source"], e.get("source_id"), e.get("event_type"),
                        Jsonb(e.get("actors") or {}), e.get("h3_cell"),
                        float(e.get("occurred_at") or time.time()),
                        e.get("magnitude"), e.get("confidence"),
                        Jsonb(e.get("payload") or {})))
                    inserted += cur.rowcount
        else:
            cur = self.conn.cursor()
            for e in events:
                cur.execute(
                    "INSERT OR IGNORE INTO raw_events(source, source_id, event_type, "
                    "actors, h3_cell, occurred_at, magnitude, confidence, payload, "
                    "ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (e["source"], e.get("source_id"), e.get("event_type"),
                     json.dumps(e.get("actors") or {}), e.get("h3_cell"),
                     float(e.get("occurred_at") or time.time()),
                     e.get("magnitude"), e.get("confidence"),
                     json.dumps(e.get("payload") or {}, default=str), time.time()))
                inserted += cur.rowcount
            self.conn.commit()
        return {"received": len(events), "inserted": inserted,
                "duplicates": len(events) - inserted}

    # ------------------------------------------------------------------- read
    def count(self, source: str | None = None) -> int:
        q = "SELECT count(*) FROM raw_events" + (" WHERE source = %s" if source else "")
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(q if source else q, (source,) if source else None)
                return int(list(cur.fetchone().values())[0])
        cur = self.conn.execute(q.replace("%s", "?"), (source,) if source else ())
        return int(cur.fetchone()[0])

    def sample(self, source: str, n: int = 3) -> list[dict]:
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute("SELECT source, source_id, event_type, h3_cell, magnitude, "
                            "confidence FROM raw_events WHERE source=%s LIMIT %s", (source, n))
                return list(cur.fetchall())
        cur = self.conn.execute(
            "SELECT source, source_id, event_type, h3_cell, magnitude, confidence "
            "FROM raw_events WHERE source=? LIMIT ?", (source, n))
        cols = ["source", "source_id", "event_type", "h3_cell", "magnitude", "confidence"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ---------------------------------------------------------------- quality
    def dup_groups(self, source: str) -> int:
        """DB-level dedup audit: (source, source_id) groups with >1 row.
        Must be 0 — the UNIQUE constraint enforces it for non-NULL ids; this
        PROVES it and catches the NULL-id edge case (UNIQUE permits multiple
        NULLs in both sqlite and PG)."""
        q = ("SELECT count(*) FROM (SELECT source_id FROM raw_events "
             "WHERE source = {p} AND source_id IS NOT NULL "
             "GROUP BY source_id HAVING count(*) > 1) d")
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(q.format(p="%s"), (source,))
                return int(list(cur.fetchone().values())[0])
        cur = self.conn.execute(q.format(p="?"), (source,))
        return int(cur.fetchone()[0])

    def null_id_rows(self, source: str) -> int:
        q = "SELECT count(*) FROM raw_events WHERE source = {p} AND source_id IS NULL"
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(q.format(p="%s"), (source,))
                return int(list(cur.fetchone().values())[0])
        cur = self.conn.execute(q.format(p="?"), (source,))
        return int(cur.fetchone()[0])

    def geo_coverage(self, source: str) -> float:
        q = ("SELECT COALESCE(AVG(CASE WHEN h3_cell IS NULL THEN 0.0 ELSE 1.0 END), 0) "
             "FROM raw_events WHERE source = {p}")
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(q.format(p="%s"), (source,))
                return float(list(cur.fetchone().values())[0])
        cur = self.conn.execute(q.format(p="?"), (source,))
        return float(cur.fetchone()[0])

    def close(self):
        self.conn.close()
