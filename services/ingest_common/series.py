"""ARGUS — time-series point store (Task 48 dependency).

Home for market/indicator series (brent_usd, embi_spread, nino34_anomaly, ...)
used by resolution rules and, later, the markets ingest worker. Same dual
backend pattern: PostgreSQL when DATABASE_URL set, SQLite otherwise.
DDL is self-applied (idempotent); db/postgres/002_series.sql mirrors it for ops.
"""
from __future__ import annotations
import os, sqlite3, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.copilot.config import get_settings

SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS series_points(
  series TEXT NOT NULL,
  ts REAL NOT NULL,
  value REAL NOT NULL,
  UNIQUE(series, ts));
CREATE INDEX IF NOT EXISTS idx_series_ts ON series_points(series, ts);
"""
PG_DDL = """
CREATE TABLE IF NOT EXISTS series_points(
  series TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  UNIQUE(series, ts));
CREATE INDEX IF NOT EXISTS idx_series_ts ON series_points(series, ts);
"""
OPS = {">": "value > {v}", ">=": "value >= {v}", "<": "value < {v}", "<=": "value <= {v}"}


class SeriesStore:
    def __init__(self, sqlite_path: str | None = None):
        s = get_settings()
        self.backend = s.backend
        if self.backend == "postgres":
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(s.database_url, autocommit=True,
                                        row_factory=dict_row)
            with self.conn.cursor() as cur:
                cur.execute(PG_DDL)
        else:
            path = sqlite_path or os.path.join(os.path.dirname(s.db), "series.db")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.executescript(SQLITE_DDL)
            self.conn.commit()

    def add_points(self, series: str, points: list[tuple[float, float]]) -> int:
        """points: [(epoch_ts, value)] — upsert-ignore on (series, ts)."""
        n = 0
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                for ts, v in points:
                    cur.execute("INSERT INTO series_points (series, ts, value) "
                                "VALUES (%s, to_timestamp(%s), %s) "
                                "ON CONFLICT (series, ts) DO NOTHING", (series, ts, v))
                    n += cur.rowcount
        else:
            cur = self.conn.cursor()
            for ts, v in points:
                cur.execute("INSERT OR IGNORE INTO series_points VALUES(?,?,?)",
                            (series, ts, v))
                n += cur.rowcount
            self.conn.commit()
        return n

    def first_crossing(self, series: str, op: str, value: float,
                       t0: float, t1: float) -> float | None:
        """Earliest ts in [t0, t1] where `value <op> threshold` holds, else None."""
        cond = OPS[op].format(v=float(value))
        if self.backend == "postgres":
            q = (f"SELECT EXTRACT(EPOCH FROM ts)::float8 AS ts FROM series_points "
                 f"WHERE series = %s AND ts >= to_timestamp(%s) AND ts <= to_timestamp(%s) "
                 f"AND {cond} ORDER BY ts LIMIT 1")
            with self.conn.cursor() as cur:
                cur.execute(q, (series, t0, t1))
                row = cur.fetchone()
            return float(row["ts"]) if row else None
        q = (f"SELECT ts FROM series_points WHERE series = ? AND ts >= ? AND ts <= ? "
             f"AND {cond} ORDER BY ts LIMIT 1")
        row = self.conn.execute(q, (series, t0, t1)).fetchone()
        return float(row[0]) if row else None

    def value_asof(self, series: str, ts: float) -> float | None:
        """Last observed value at or before ts (ask-time snapshot primitive)."""
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute("SELECT value FROM series_points WHERE series=%s AND "
                            "ts <= to_timestamp(%s) ORDER BY ts DESC LIMIT 1", (series, ts))
                row = cur.fetchone()
            return float(row["value"]) if row else None
        row = self.conn.execute("SELECT value FROM series_points WHERE series=? AND "
                                "ts <= ? ORDER BY ts DESC LIMIT 1", (series, ts)).fetchone()
        return float(row[0]) if row else None

    def list_series(self) -> list[str]:
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute("SELECT DISTINCT series FROM series_points ORDER BY series")
                return [r["series"] for r in cur.fetchall()]
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT series FROM series_points ORDER BY series").fetchall()]

    def count(self, series: str) -> int:
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute("SELECT count(*) AS n FROM series_points WHERE series=%s",
                            (series,))
                return int(cur.fetchone()["n"])
        return int(self.conn.execute(
            "SELECT count(*) FROM series_points WHERE series=?", (series,)).fetchone()[0])

    def close(self):
        self.conn.close()
