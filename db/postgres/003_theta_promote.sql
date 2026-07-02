-- ARGUS — Task 53: champion theta flag on the versions registry
ALTER TABLE theta_versions ADD COLUMN IF NOT EXISTS promoted BOOLEAN DEFAULT FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS one_promoted_theta
  ON theta_versions (promoted) WHERE promoted;
