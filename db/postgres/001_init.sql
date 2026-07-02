-- ARGUS Copilot — PostgreSQL schema v1 (production mirror of services/copilot/store.py)
-- Apply: psql $DATABASE_URL -f db/postgres/001_init.sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- identity & sessions -------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username      TEXT UNIQUE NOT NULL,
  clearance     TEXT NOT NULL DEFAULT 'OPEN',         -- OPEN | OFFICIAL | SECRET
  persona       TEXT NOT NULL DEFAULT 'analyst',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT PRIMARY KEY,
  user_id       UUID REFERENCES users(id),
  persona       TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS messages (
  id            TEXT PRIMARY KEY,
  session_id    TEXT REFERENCES sessions(id),
  role          TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content       TEXT NOT NULL,
  intent        TEXT,
  manifest_id   TEXT,
  latency_ms    INTEGER,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

-- question registry & forecast ledger (blueprint §7) -------------------------
CREATE TABLE IF NOT EXISTS questions (
  key           TEXT PRIMARY KEY,                      -- e.g. ME_war_1y
  text          TEXT NOT NULL,
  domain        TEXT NOT NULL,
  horizon       TEXT,
  resolution_rule TEXT,                                -- how it auto-resolves
  resolved      BOOLEAN DEFAULT FALSE,
  outcome       SMALLINT,                              -- 0/1 when resolved
  resolved_at   TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS forecast_ledger (
  manifest_id   TEXT PRIMARY KEY,
  key           TEXT REFERENCES questions(key),
  probability   DOUBLE PRECISION NOT NULL CHECK (probability BETWEEN 0 AND 1),
  band_lo       DOUBLE PRECISION,
  band_hi       DOUBLE PRECISION,
  verdict       TEXT,                                  -- ROBUST|SENSITIVE|FRAGILE
  theta_hash    TEXT NOT NULL,
  engine_ver    TEXT NOT NULL DEFAULT '1.0.0',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ledger_key_time ON forecast_ledger(key, created_at);

-- runs (counterfactual / policy / pipeline) ----------------------------------
CREATE TABLE IF NOT EXISTS runs (
  manifest_id   TEXT PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('counterfactual','policy','pipeline','forecast')),
  payload       JSONB NOT NULL,
  theta_hash    TEXT NOT NULL,
  seed          INTEGER NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_runs_kind ON runs(kind, created_at);

-- evidence layer (Phase 1-2 mirror of data/situation.json) -------------------
CREATE TABLE IF NOT EXISTS facts (
  id            TEXT PRIMARY KEY,                      -- F1..Fn
  domain        TEXT NOT NULL,
  text          TEXT NOT NULL,
  source        TEXT NOT NULL,
  valid_from    DATE,
  ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS signals (
  name          TEXT PRIMARY KEY,
  strength      SMALLINT CHECK (strength BETWEEN 0 AND 100),
  reliability   SMALLINT CHECK (reliability BETWEEN 0 AND 100),
  growth        TEXT, horizon TEXT, impact TEXT,
  fact_ids      TEXT[]
);

-- ingestion staging (Phase-2 GDELT/ACLED connectors land here) ---------------
CREATE TABLE IF NOT EXISTS raw_events (
  id            BIGSERIAL PRIMARY KEY,
  source        TEXT NOT NULL,                         -- gdelt|acled|manual
  source_id     TEXT,
  event_type    TEXT,
  actors        JSONB,
  h3_cell       TEXT,
  occurred_at   TIMESTAMPTZ,
  magnitude     DOUBLE PRECISION,
  confidence    DOUBLE PRECISION,
  payload       JSONB NOT NULL,
  ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_events_time ON raw_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_raw_events_cell ON raw_events(h3_cell);

-- audit (append-only; blueprint §21) -----------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
  id            BIGSERIAL PRIMARY KEY,
  actor         TEXT NOT NULL,
  action        TEXT NOT NULL,
  detail        TEXT,
  prev_hash     TEXT,                                  -- hash chain
  entry_hash    TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- theta registry --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS theta_versions (
  theta_hash    TEXT PRIMARY KEY,
  names         TEXT[] NOT NULL,
  vals          DOUBLE PRECISION[] NOT NULL,
  brier_replay  DOUBLE PRECISION,
  trained_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes         TEXT
);
