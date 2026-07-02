-- Task 87: analyst dissents / right-of-reply, attached to a forecast key.
CREATE TABLE IF NOT EXISTS dissents (
  id          text PRIMARY KEY,
  fkey        text NOT NULL,
  author      text NOT NULL,
  clearance   text,
  text        text NOT NULL,
  signature   text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dissents_fkey_idx ON dissents (fkey);
