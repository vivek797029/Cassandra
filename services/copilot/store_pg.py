"""ARGUS Copilot — PostgreSQL persistence driver (Task 40).

Same interface as services.copilot.store.Store, backed by psycopg3 against the
schema in db/postgres/001_init.sql (applied idempotently on startup).

Selection: set DATABASE_URL (e.g. postgresql://argus:argus-dev-only@localhost:5432/argus)
and services.copilot.store.get_store() returns PgStore automatically.

All SQL lives in the module-level SQL dict so tests can validate every
statement under the real PostgreSQL grammar (pglast) without a server.
"""
from __future__ import annotations
import json, os, time, uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "..",
                           "db", "postgres", "001_init.sql")

SQL = {
    "ensure_session":
        "INSERT INTO sessions (id, persona) VALUES (%s, %s) "
        "ON CONFLICT (id) DO NOTHING",
    "log_message":
        "INSERT INTO messages (id, session_id, role, content, intent, manifest_id, latency_ms) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
    "session_messages":
        "SELECT role, content, intent, manifest_id, latency_ms, "
        "       EXTRACT(EPOCH FROM created_at)::float8 AS created_at "
        "FROM messages WHERE session_id = %s ORDER BY created_at",
    "record_run":
        "INSERT INTO runs (manifest_id, kind, payload, theta_hash, seed) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (manifest_id) DO UPDATE SET "
        "  payload = EXCLUDED.payload, theta_hash = EXCLUDED.theta_hash, "
        "  seed = EXCLUDED.seed",
    "get_run":
        "SELECT manifest_id, kind, payload, theta_hash, seed, "
        "       EXTRACT(EPOCH FROM created_at)::float8 AS created_at "
        "FROM runs WHERE manifest_id = %s",
    "audit":
        "INSERT INTO audit_log (actor, action, detail) VALUES (%s, %s, %s)",
    "audit_count":
        "SELECT count(*)::int AS n FROM audit_log",
    "answers_stats":
        "SELECT count(*)::int AS answers_total, "
        "       COALESCE(avg(latency_ms), 0)::float8 AS avg_latency_ms "
        "FROM messages WHERE role = 'assistant'",
    "ledger_record":
        "INSERT INTO forecast_ledger (manifest_id, key, probability, band_lo, band_hi, "
        "theta_hash) VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (manifest_id) DO UPDATE SET probability = EXCLUDED.probability",
    "ledger_latest":
        "SELECT DISTINCT ON (key) key, probability, band_lo, band_hi, theta_hash, "
        "EXTRACT(EPOCH FROM created_at)::float8 AS created_at "
        "FROM forecast_ledger ORDER BY key, created_at DESC",
    "bands_save":
        "INSERT INTO band_cache (theta_hash, key, center, lo, hi, conformal_q80, n_paths, fidelity) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (theta_hash, key) DO UPDATE SET "
        "  center = EXCLUDED.center, lo = EXCLUDED.lo, hi = EXCLUDED.hi, "
        "  conformal_q80 = EXCLUDED.conformal_q80, "
        "  n_paths = EXCLUDED.n_paths, fidelity = EXCLUDED.fidelity, computed_at = now()",
    "bands_get":
        "SELECT key, center, lo, hi, conformal_q80, n_paths, fidelity, "
        "       EXTRACT(EPOCH FROM computed_at)::float8 AS computed_at "
        "FROM band_cache WHERE theta_hash = %s",
    "dissent_save":
        "INSERT INTO dissents (id, fkey, author, clearance, text, signature, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s))",
    "dissents_for":
        "SELECT id, author, clearance, text, signature, "
        "       EXTRACT(EPOCH FROM created_at)::float8 AS created_at "
        "FROM dissents WHERE fkey = %s ORDER BY created_at",
}


class PgStore:
    """Drop-in PostgreSQL replacement for the SQLite Store (same 6 methods)."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ["DATABASE_URL"]
        self.conn = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)
        self._ensure_schema()

    def _ensure_schema(self):
        """Apply all db/postgres/*.sql migrations in order (all idempotent)."""
        import glob
        mig_dir = os.path.dirname(SCHEMA_FILE)
        with self.conn.cursor() as cur:
            for path in sorted(glob.glob(os.path.join(mig_dir, "*.sql"))):
                with open(path) as f:
                    cur.execute(f.read())

    # -- sessions / messages ---------------------------------------------------
    def ensure_session(self, session_id: str | None, persona: str) -> str:
        sid = session_id or uuid.uuid4().hex[:12]
        with self.conn.cursor() as cur:
            cur.execute(SQL["ensure_session"], (sid, persona))
        return sid

    def log_message(self, session_id: str, role: str, content: str,
                    intent: str = "", manifest_id: str = "", latency_ms: int = 0):
        with self.conn.cursor() as cur:
            cur.execute(SQL["log_message"],
                        (uuid.uuid4().hex[:12], session_id, role, content[:8000],
                         intent, manifest_id, latency_ms))

    def session_messages(self, session_id: str) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(SQL["session_messages"], (session_id,))
            return list(cur.fetchall())

    # -- ledgers -----------------------------------------------------------------
    def record_run(self, manifest_id: str, kind: str, payload: dict,
                   theta_hash: str, seed: int):
        with self.conn.cursor() as cur:
            cur.execute(SQL["record_run"],
                        (manifest_id, kind, Jsonb(json.loads(
                            json.dumps(payload, default=str))), theta_hash, seed))

    def get_run(self, manifest_id: str) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(SQL["get_run"], (manifest_id,))
            row = cur.fetchone()
        return dict(row) if row else None

    def audit(self, actor: str, action: str, detail: str = ""):
        with self.conn.cursor() as cur:
            cur.execute(SQL["audit"], (actor, action, detail[:2000]))

    # theta versions (Task 53) ---------------------------------------------------
    def theta_save(self, theta_hash: str, names: list[str], vals: list[float],
                   brier_replay: float | None = None, notes: str = ""):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO theta_versions (theta_hash, names, vals, brier_replay, notes) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (theta_hash) DO UPDATE SET "
                "brier_replay = EXCLUDED.brier_replay, notes = EXCLUDED.notes",
                (theta_hash, names, vals, brier_replay, notes))

    def theta_promote(self, theta_hash: str):
        with self.conn.cursor() as cur:
            cur.execute("UPDATE theta_versions SET promoted = FALSE")
            cur.execute("UPDATE theta_versions SET promoted = TRUE WHERE theta_hash = %s",
                        (theta_hash,))
            if cur.rowcount == 0:
                raise KeyError(theta_hash)

    def theta_promoted(self) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT theta_hash, names, vals, brier_replay, notes, "
                        "EXTRACT(EPOCH FROM trained_at)::float8 AS trained_at "
                        "FROM theta_versions WHERE promoted LIMIT 1")
            row = cur.fetchone()
        return dict(row) if row else None

    def theta_list(self) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT theta_hash, brier_replay, promoted, notes, "
                        "EXTRACT(EPOCH FROM trained_at)::float8 AS trained_at "
                        "FROM theta_versions ORDER BY trained_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def ledger_record(self, manifest_id: str, key: str, probability: float,
                      band_lo: float | None, band_hi: float | None, theta_hash: str):
        with self.conn.cursor() as cur:
            cur.execute(SQL["ledger_record"], (manifest_id, key, probability,
                                               band_lo, band_hi, theta_hash))

    def ledger_latest(self) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(SQL["ledger_latest"])
            return [dict(r) for r in cur.fetchall()]

    def answers_stats(self) -> dict:
        with self.conn.cursor() as cur:
            cur.execute(SQL["answers_stats"])
            row = cur.fetchone()
        return {"answers_total": int(row["answers_total"]),
                "avg_latency_ms": round(float(row["avg_latency_ms"]), 1)}

    # band cache (Task 83) -----------------------------------------------------
    def bands_save(self, theta_hash: str, bands: dict, n_paths: int, fidelity: str = "full"):
        with self.conn.cursor() as cur:
            for key, b in bands.items():
                cur.execute(SQL["bands_save"], (theta_hash, key, b.get("center"), b["lo"],
                                                b["hi"], b.get("conformal_q80"), n_paths, fidelity))

    def bands_get(self, theta_hash: str) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(SQL["bands_get"], (theta_hash,))
            rows = cur.fetchall()
        if not rows:
            return None
        bands = {r["key"]: {"center": r["center"], "lo": r["lo"], "hi": r["hi"],
                            "conformal_q80": r["conformal_q80"]} for r in rows}
        return {"theta_hash": theta_hash, "bands": bands, "n_paths": rows[0]["n_paths"],
                "fidelity": rows[0]["fidelity"], "computed_at": rows[0]["computed_at"]}

    # dissents / right-of-reply (Task 87) --------------------------------------
    def dissent_save(self, fkey: str, author: str, clearance: str, text: str,
                     signature: str, created_at: float | None = None) -> str:
        import time as _t
        import uuid as _u
        did = _u.uuid4().hex[:16]
        ts = _t.time() if created_at is None else created_at
        with self.conn.cursor() as cur:
            cur.execute(SQL["dissent_save"],
                        (did, fkey, author, clearance, text[:4000], signature, ts))
        return did

    def dissents_for(self, fkey: str) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(SQL["dissents_for"], (fkey,))
            return [dict(r) for r in cur.fetchall()]

    def close(self):
        self.conn.close()
