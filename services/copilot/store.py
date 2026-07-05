"""ARGUS Copilot — persistence layer.
SQLite by default (works everywhere, incl. this repo's demo); set DATABASE_URL
postgres://... in production (same schema, see db/postgres/001_init.sql).

Concurrency (Task 69 hardening): the SQLite path is exercised by uvicorn's
sync-endpoint threadpool (many threads share one process) and, when scaled,
by multiple worker processes sharing one file. To survive 100 concurrent users
without 500s we:
  * open in WAL mode with synchronous=NORMAL — concurrent readers + one writer,
    safe across processes;
  * set busy_timeout so a contended write waits for the lock instead of raising
    "database is locked";
  * guard the single shared connection with a process-wide RLock so concurrent
    threads can't trip "recursive use of cursors" / interleave a transaction.
DB ops here are sub-millisecond, so the lock does not move the latency SLO."""
from __future__ import annotations
import os, json, sqlite3, time, uuid, threading

from services.copilot.config import get_settings

DDL = """
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, persona TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
  intent TEXT, manifest_id TEXT, latency_ms INTEGER, created_at REAL);
CREATE TABLE IF NOT EXISTS forecast_ledger(
  manifest_id TEXT PRIMARY KEY, key TEXT, probability REAL,
  band_lo REAL, band_hi REAL, theta_hash TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS runs(
  manifest_id TEXT PRIMARY KEY, kind TEXT, payload TEXT,
  theta_hash TEXT, seed INTEGER, created_at REAL);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT,
  detail TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS theta_versions(
  theta_hash TEXT PRIMARY KEY, names TEXT, vals TEXT,
  brier_replay REAL, promoted INTEGER DEFAULT 0,
  notes TEXT, trained_at REAL);
CREATE TABLE IF NOT EXISTS band_cache(
  theta_hash TEXT, key TEXT, center REAL, lo REAL, hi REAL, conformal_q80 REAL,
  n_paths INTEGER, fidelity TEXT, computed_at REAL,
  PRIMARY KEY (theta_hash, key));
CREATE TABLE IF NOT EXISTS dissents(
  id TEXT PRIMARY KEY, fkey TEXT, author TEXT, clearance TEXT,
  text TEXT, signature TEXT, created_at REAL);
"""

class Store:
    def __init__(self, path: str | None = None):
        # NOTE: default lives on local disk — SQLite locking fails on network mounts.
        path = path or get_settings().db
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
        # concurrency pragmas: WAL + bounded busy wait (survives multi-thread /
        # multi-worker writes from the /v1/ask path under load).
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(DDL)
        self.conn.commit()

    # sessions / messages -----------------------------------------------------
    def ensure_session(self, session_id: str | None, persona: str) -> str:
        sid = session_id or uuid.uuid4().hex[:12]
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?)",
                              (sid, persona, time.time()))
            self.conn.commit()
        return sid

    def log_message(self, session_id: str, role: str, content: str,
                    intent: str = "", manifest_id: str = "", latency_ms: int = 0):
        with self._lock:
            self.conn.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)",
                              (uuid.uuid4().hex[:12], session_id, role, content[:8000],
                               intent, manifest_id, latency_ms, time.time()))
            self.conn.commit()

    def session_messages(self, session_id: str) -> list[dict]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT role, content, intent, manifest_id, latency_ms, created_at "
                "FROM messages WHERE session_id=? ORDER BY created_at", (session_id,))
            rows = cur.fetchall()
        return [dict(zip(["role", "content", "intent", "manifest_id", "latency_ms",
                          "created_at"], r)) for r in rows]

    # ledgers ------------------------------------------------------------------
    def record_run(self, manifest_id: str, kind: str, payload: dict,
                   theta_hash: str, seed: int):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?)",
                              (manifest_id, kind, json.dumps(payload, default=str)[:20000],
                               theta_hash, seed, time.time()))
            self.conn.commit()

    def get_run(self, manifest_id: str) -> dict | None:
        with self._lock:
            cur = self.conn.execute(
                "SELECT manifest_id, kind, payload, theta_hash, seed, created_at "
                "FROM runs WHERE manifest_id=?", (manifest_id,))
            r = cur.fetchone()
        if not r:
            return None
        return {"manifest_id": r[0], "kind": r[1], "payload": json.loads(r[2]),
                "theta_hash": r[3], "seed": r[4], "created_at": r[5]}

    def audit(self, actor: str, action: str, detail: str = ""):
        with self._lock:
            self.conn.execute("INSERT INTO audit_log(actor,action,detail,created_at) "
                              "VALUES(?,?,?,?)", (actor, action, detail[:2000], time.time()))
            self.conn.commit()

    # theta versions (Task 53) ---------------------------------------------------
    def theta_save(self, theta_hash: str, names: list[str], vals: list[float],
                   brier_replay: float | None = None, notes: str = ""):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO theta_versions VALUES(?,?,?,?,"
                              "COALESCE((SELECT promoted FROM theta_versions WHERE "
                              "theta_hash=?),0),?,?)",
                              (theta_hash, json.dumps(names), json.dumps(vals),
                               brier_replay, theta_hash, notes, time.time()))
            self.conn.commit()

    def theta_promote(self, theta_hash: str):
        with self._lock:
            self.conn.execute("UPDATE theta_versions SET promoted=0")
            cur = self.conn.execute("UPDATE theta_versions SET promoted=1 WHERE theta_hash=?",
                                    (theta_hash,))
            self.conn.commit()
            rowcount = cur.rowcount
        if rowcount == 0:
            raise KeyError(theta_hash)

    def theta_promoted(self) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT theta_hash, names, vals, brier_replay, notes, trained_at "
                "FROM theta_versions WHERE promoted=1 LIMIT 1").fetchone()
        if not row:
            return None
        return {"theta_hash": row[0], "names": json.loads(row[1]),
                "vals": json.loads(row[2]), "brier_replay": row[3],
                "notes": row[4], "trained_at": row[5]}

    def theta_list(self) -> list[dict]:
        with self._lock:
            cur = self.conn.execute("SELECT theta_hash, brier_replay, promoted, notes, "
                                    "trained_at FROM theta_versions ORDER BY trained_at DESC")
            rows = cur.fetchall()
        cols = ["theta_hash", "brier_replay", "promoted", "notes", "trained_at"]
        return [dict(zip(cols, r)) for r in rows]

    # forecast ledger (Task 50) ------------------------------------------------
    def ledger_record(self, manifest_id: str, key: str, probability: float,
                      band_lo: float | None, band_hi: float | None, theta_hash: str):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO forecast_ledger VALUES(?,?,?,?,?,?,?)",
                              (manifest_id, key, probability, band_lo, band_hi,
                               theta_hash, time.time()))
            self.conn.commit()

    def ledger_latest(self) -> list[dict]:
        """Latest prediction per key (for scoring against resolved outcomes)."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT l.key, l.probability, l.band_lo, l.band_hi, l.theta_hash, l.created_at "
                "FROM forecast_ledger l JOIN (SELECT key, MAX(created_at) m FROM forecast_ledger "
                "GROUP BY key) x ON l.key = x.key AND l.created_at = x.m")
            rows = cur.fetchall()
        cols = ["key", "probability", "band_lo", "band_hi", "theta_hash", "created_at"]
        return [dict(zip(cols, r)) for r in rows]

    def answers_stats(self) -> dict:
        with self._lock:
            cur = self.conn.execute("SELECT COUNT(*), COALESCE(AVG(latency_ms),0) "
                                    "FROM messages WHERE role='assistant'")
            n, avg = cur.fetchone()
        return {"answers_total": int(n), "avg_latency_ms": round(float(avg), 1)}

    # band cache (Task 83) -----------------------------------------------------
    def bands_save(self, theta_hash: str, bands: dict, n_paths: int, fidelity: str = "full"):
        now = time.time()
        with self._lock:
            for key, b in bands.items():
                self.conn.execute(
                    "INSERT OR REPLACE INTO band_cache VALUES(?,?,?,?,?,?,?,?,?)",
                    (theta_hash, key, b.get("center"), b["lo"], b["hi"],
                     b.get("conformal_q80"), n_paths, fidelity, now))
            self.conn.commit()

    def bands_get(self, theta_hash: str) -> dict | None:
        with self._lock:
            cur = self.conn.execute(
                "SELECT key, center, lo, hi, conformal_q80, n_paths, fidelity, computed_at "
                "FROM band_cache WHERE theta_hash=?", (theta_hash,))
            rows = cur.fetchall()
        if not rows:
            return None
        bands = {r[0]: {"center": r[1], "lo": r[2], "hi": r[3], "conformal_q80": r[4]}
                 for r in rows}
        return {"theta_hash": theta_hash, "bands": bands, "n_paths": rows[0][5],
                "fidelity": rows[0][6], "computed_at": rows[0][7]}

    def bands_delete(self, theta_hash: str) -> int:
        """Flush cached bands for one theta (ops tooling: recover from a stale or
        corrupt band cache without touching the rest of the store). Returns rows
        removed. Also used by tests to leave shared backends clean."""
        with self._lock:
            cur = self.conn.execute("DELETE FROM band_cache WHERE theta_hash=?",
                                    (theta_hash,))
            self.conn.commit()
        return cur.rowcount

    # dissents / right-of-reply (Task 87) --------------------------------------
    def dissent_save(self, fkey: str, author: str, clearance: str, text: str,
                     signature: str, created_at: float | None = None) -> str:
        did = uuid.uuid4().hex[:16]
        ts = time.time() if created_at is None else created_at
        with self._lock:
            self.conn.execute("INSERT INTO dissents VALUES(?,?,?,?,?,?,?)",
                              (did, fkey, author, clearance, text[:4000], signature, ts))
            self.conn.commit()
        return did

    def dissents_for(self, fkey: str) -> list[dict]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, author, clearance, text, signature, created_at "
                "FROM dissents WHERE fkey=? ORDER BY created_at", (fkey,))
            rows = cur.fetchall()
        cols = ["id", "author", "clearance", "text", "signature", "created_at"]
        return [dict(zip(cols, r)) for r in rows]

STORE = None

def get_store():
    """Factory: PostgreSQL when DATABASE_URL is set (services/copilot/store_pg.py),
    SQLite otherwise. Both expose the same 6-method interface."""
    global STORE
    if STORE is None:
        s = get_settings()
        if s.backend == "postgres":
            from services.copilot.store_pg import PgStore
            STORE = PgStore(s.database_url)
        else:
            STORE = Store(s.db)
    return STORE
