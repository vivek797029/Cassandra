-- ARGUS — series points (markets/indicators) — mirrors services/ingest_common/series.py
CREATE TABLE IF NOT EXISTS series_points(
  series TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  UNIQUE(series, ts));
CREATE INDEX IF NOT EXISTS idx_series_ts ON series_points(series, ts);
