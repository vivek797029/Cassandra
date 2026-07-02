"""ARGUS — question registry store (Task 47).

Every forecastable question becomes a versioned, resolvable row. Resolution
rules are typed JSON consumed by the resolver (Task 48); the registry is the
source of truth that feeds calibration training with REAL resolved events.

Backends: PostgreSQL `questions` table (db/postgres/001_init.sql) when
DATABASE_URL is set; SQLite mirror otherwise. Same interface.
"""
from __future__ import annotations
import json, os, sqlite3, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.copilot.config import get_settings

SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS questions(
  key TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  domain TEXT NOT NULL,
  horizon TEXT,
  resolution_rule TEXT,
  resolved INTEGER DEFAULT 0,
  outcome INTEGER,
  resolved_at REAL);
"""

class QuestionRegistry:
    def __init__(self, sqlite_path: str | None = None):
        s = get_settings()
        self.backend = s.backend
        if self.backend == "postgres":
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(s.database_url, autocommit=True,
                                        row_factory=dict_row)
        else:
            path = sqlite_path or os.path.join(os.path.dirname(s.db), "registry.db")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.executescript(SQLITE_DDL)
            self.conn.commit()

    # -------------------------------------------------------------- helpers --
    def _row_to_dict(self, row) -> dict:
        if isinstance(row, dict):                       # PG dict_row
            d = dict(row)
            if d.get("resolved_at") is not None and not isinstance(d["resolved_at"], (int, float)):
                d["resolved_at"] = d["resolved_at"].timestamp()
            d["resolved"] = bool(d["resolved"])
            return d
        cols = ["key", "text", "domain", "horizon", "resolution_rule",
                "resolved", "outcome", "resolved_at"]
        d = dict(zip(cols, row))
        d["resolved"] = bool(d["resolved"])
        return d

    # ---------------------------------------------------------------- write --
    def create(self, key: str, text: str, domain: str, horizon: str | None = None,
               resolution_rule: dict | None = None, if_exists: str = "error") -> bool:
        """Returns True if inserted. if_exists: 'error' | 'ignore'."""
        rule = json.dumps(resolution_rule or {"type": "manual"})
        if self.backend == "postgres":
            q = ("INSERT INTO questions (key, text, domain, horizon, resolution_rule) "
                 "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING")
            with self.conn.cursor() as cur:
                cur.execute(q, (key, text, domain, horizon, rule))
                inserted = cur.rowcount > 0
        else:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO questions(key, text, domain, horizon, "
                "resolution_rule) VALUES(?,?,?,?,?)", (key, text, domain, horizon, rule))
            self.conn.commit()
            inserted = cur.rowcount > 0
        if not inserted and if_exists == "error":
            raise KeyError(f"question '{key}' already exists")
        return inserted

    def resolve(self, key: str, outcome: int) -> dict:
        if self.get(key) is None:
            raise KeyError(key)
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute("UPDATE questions SET resolved = TRUE, outcome = %s, "
                            "resolved_at = now() WHERE key = %s", (int(outcome), key))
        else:
            self.conn.execute("UPDATE questions SET resolved = 1, outcome = ?, "
                              "resolved_at = ? WHERE key = ?",
                              (int(outcome), time.time(), key))
            self.conn.commit()
        return self.get(key)

    # ----------------------------------------------------------------- read --
    def get(self, key: str) -> dict | None:
        q = ("SELECT key, text, domain, horizon, resolution_rule, resolved, outcome, "
             "resolved_at FROM questions WHERE key = {p}")
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(q.format(p="%s"), (key,))
                row = cur.fetchone()
        else:
            row = self.conn.execute(q.format(p="?"), (key,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, resolved: bool | None = None, domain: str | None = None) -> list[dict]:
        q = ("SELECT key, text, domain, horizon, resolution_rule, resolved, outcome, "
             "resolved_at FROM questions WHERE 1=1")
        args: list = []
        ph = "%s" if self.backend == "postgres" else "?"
        if resolved is not None:
            q += f" AND resolved = {ph}"
            args.append(bool(resolved) if self.backend == "postgres" else int(resolved))
        if domain:
            q += f" AND domain = {ph}"
            args.append(domain)
        q += " ORDER BY key"
        if self.backend == "postgres":
            with self.conn.cursor() as cur:
                cur.execute(q, tuple(args))
                rows = cur.fetchall()
        else:
            rows = self.conn.execute(q, tuple(args)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def close(self):
        self.conn.close()


# --------------------------------------------------------------------- seed --
DOMAIN_BY_PREFIX = {"ME_": "security", "UA_": "security", "TW_": "security",
                    "Hormuz": "security", "Brent": "economic", "Global": "economic",
                    "Inflation": "economic", "EM_": "economic", "Dem_": "political"}

SEED_RULES = {
    "Brent_gt120_1y": {"type": "series_threshold", "series": "brent_usd",
                       "op": ">", "value": 120, "by": "2027-06-11"},
    "Brent_gt150_2y": {"type": "series_threshold", "series": "brent_usd",
                       "op": ">", "value": 150, "by": "2028-06-11"},
    "ME_war_1y": {"type": "event_count", "source": "acled",
                  "event_types": ["battles", "explosions_remote_violence"],
                  "countries": ["Iran", "Israel"], "window_days": 28,
                  "op": ">=", "threshold": 40, "by": "2027-06-11"},
    "Dem_House_Nov2026": {"type": "manual", "by": "2026-11-10"},
}

def seed_from_engines(reg: QuestionRegistry) -> int:
    """Idempotently register the engine question set. Returns #inserted."""
    from services.copilot.engines import QUESTION_TEXT, HORIZON
    n = 0
    for key, text in QUESTION_TEXT.items():
        domain = next((d for p, d in DOMAIN_BY_PREFIX.items() if key.startswith(p)),
                      "political")
        n += reg.create(key, text, domain, HORIZON.get(key),
                        SEED_RULES.get(key, {"type": "manual"}), if_exists="ignore")
    return n
