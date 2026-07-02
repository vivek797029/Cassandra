-- Task 83: full-fidelity band cache (nightly worker writes; engines read on startup).
CREATE TABLE IF NOT EXISTS band_cache (
  theta_hash    text NOT NULL,
  key           text NOT NULL,
  center        double precision,
  lo            double precision,
  hi            double precision,
  conformal_q80 double precision,
  n_paths       integer,
  fidelity      text,
  computed_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (theta_hash, key)
);
