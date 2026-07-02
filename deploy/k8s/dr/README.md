# ARGUS DR — Active-Active (multi-cluster) Runbook

**Targets:** RPO **< 15 min** (streaming replication keeps steady-state lag near zero),
RTO **< 15 min** (drill below). Two clusters, A (primary region) and B (standby region).

## Topology
- **Postgres:** `pg-primary` (cluster A) streams WAL to `pg-standby` (cluster B) via
  `postgresql-dr.yaml` (`wal_level=replica`, `max_wal_senders`, `primary_conninfo`,
  `synchronous_commit=remote_write`). The standby is a read-only hot standby.
- **API (active-active):** the ARGUS Helm release is deployed to **both** clusters. Both
  serve reads from their local engine + cache; the write path (sessions, dissents, theta
  promotion) targets the current primary's `DATABASE_URL`. A global LB / service mesh routes
  users to the nearest healthy cluster.
- **Manifest sync:** GitOps — the same chart + manifests are reconciled to both clusters
  (Argo CD / Flux), so config never drifts between regions. `kubectl --context A apply` /
  `--context B apply` is the manual fallback.

## Failover drill (run quarterly; target < 15 min RPO/RTO)
1. **Detect** primary loss: `ArgusTargetMissing` / `ArgusEngineDown` alerts fire (Task 81);
   confirm cluster A `pg-primary` is unreachable.
2. **Promote standby** (cluster B): `kubectl --context B -n argus exec pg-standby-0 --
   pg_ctl promote` (removes `standby.signal`). Verify `SELECT pg_is_in_recovery()` → `f`.
3. **Repoint writes:** update the `argus-secrets` `DATABASE_URL` in cluster B to `pg-standby`
   (now primary) and roll the API: `kubectl --context B -n argus rollout restart deploy`.
4. **Shift traffic:** flip the global LB / DNS weight to cluster B.
5. **Verify:** `curl https://argus.internal/readyz` → `ready`; run a forecast + a dissent
   write; confirm `/metrics` healthy.
6. **Measure RPO:** compare last replicated WAL LSN to the last primary commit; record the
   gap. Steady-state streaming keeps this **< 15 min** (typically seconds).
7. **Re-establish DR:** rebuild old primary as a new standby (`pg_basebackup -R`) so A/B are
   protected again.

## Rollback / failback
Once cluster A is healthy, base-backup it from the current primary, let it catch up, then
schedule a planned switchover during a maintenance window (reverse of the drill).

## Record
File each drill result (date, measured RPO, RTO, issues) alongside `docs/RUNBOOK.md`.
Last drill: _record here_.
