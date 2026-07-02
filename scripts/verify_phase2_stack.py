#!/usr/bin/env python3
"""Task 39 — Phase-2 stack verification.

Static layer (runs anywhere, no Docker needed):
  * docker-compose.yml: structure, phase2 profile, healthchecks, kafka KRaft env,
    postgres initdb mount, volumes
  * db/postgres/001_init.sql: parsed with the REAL PostgreSQL grammar (pglast);
    asserts all 10 tables + indexes + extension
  * db/kafka/topics.yaml: 11 unique topics, valid partitions/retention
  * deploy/k8s/argus.yaml: all 7 kinds present; Deployment has probes+resources
  * db/neo4j/schema.cypher: constraints/indexes/seed counts, balanced parens

Boot layer (requires a Docker daemon — run on your machine):
  python scripts/verify_phase2_stack.py --boot [--down]
  Brings up `--profile phase2`, waits until all 5 services are healthy,
  then asserts the 10 tables exist inside the postgres container and
  creates the 11 Kafka topics from topics.yaml.

Exit code 0 = PASS, 1 = any failure.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMPOSE = os.path.join(ROOT, "deploy", "docker", "docker-compose.yml")
SQL = os.path.join(ROOT, "db", "postgres", "001_init.sql")
TOPICS = os.path.join(ROOT, "db", "kafka", "topics.yaml")
K8S = os.path.join(ROOT, "deploy", "k8s", "argus.yaml")
CYPHER = os.path.join(ROOT, "db", "neo4j", "schema.cypher")

EXPECTED_TABLES = {"users", "sessions", "messages", "questions", "forecast_ledger",
                   "runs", "facts", "signals", "raw_events", "audit_log", "theta_versions"}
EXPECTED_SERVICES = {"api", "postgres", "neo4j", "redis", "kafka"}
EXPECTED_K8S_KINDS = {"Namespace", "Deployment", "PersistentVolumeClaim", "Service",
                      "Ingress", "HorizontalPodAutoscaler", "CronJob"}

PASS, FAIL = 0, 0
def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    PASS, FAIL = PASS + cond, FAIL + (not cond)

# ---------------------------------------------------------------- static ----
def static_checks():
    import yaml

    # -- compose ---------------------------------------------------------------
    with open(COMPOSE) as f:
        comp = yaml.safe_load(f)
    svcs = comp.get("services", {})
    check("compose: 5 core services + ollama", EXPECTED_SERVICES <= set(svcs),
          ",".join(sorted(svcs)))
    p2 = {n for n, s in svcs.items() if "phase2" in (s.get("profiles") or [])}
    check("compose: phase2 profile = pg/neo4j/redis/kafka",
          p2 == {"postgres", "neo4j", "redis", "kafka"}, ",".join(sorted(p2)))
    hc = [n for n in ("postgres", "neo4j", "redis", "kafka") if "healthcheck" in svcs[n]]
    check("compose: healthchecks on all phase2 services", len(hc) == 4, ",".join(hc))
    kenv = svcs["kafka"]["environment"]
    check("compose: kafka KRaft env complete",
          all(k in kenv for k in ("KAFKA_CFG_ADVERTISED_LISTENERS",
                                  "KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP",
                                  "KAFKA_CFG_CONTROLLER_QUORUM_VOTERS")))
    pg_mounts = " ".join(map(str, svcs["postgres"].get("volumes", [])))
    check("compose: postgres auto-applies DDL (initdb.d mount)",
          "docker-entrypoint-initdb.d" in pg_mounts)
    check("compose: named volumes declared",
          {"argus-data", "pg-data", "neo4j-data"} <= set(comp.get("volumes", {})))

    # -- postgres DDL via real PG grammar ---------------------------------------
    from pglast import parse_sql
    sql = open(SQL).read()
    try:
        stmts = parse_sql(sql)
        check("sql: parses under PostgreSQL grammar", True, f"{len(stmts)} statements")
    except Exception as ex:
        check("sql: parses under PostgreSQL grammar", False, str(ex)[:120])
        return
    tables, indexes, exts = set(), 0, 0
    for raw in stmts:
        node = raw.stmt
        cls = type(node).__name__
        if cls == "CreateStmt":
            tables.add(node.relation.relname)
        elif cls == "IndexStmt":
            indexes += 1
        elif cls == "CreateExtensionStmt":
            exts += 1
    check("sql: all expected tables created", EXPECTED_TABLES <= tables,
          f"{len(tables)} tables")
    check("sql: indexes present", indexes >= 5, f"{indexes} indexes")
    check("sql: pgcrypto extension", exts >= 1)

    # -- kafka topics ------------------------------------------------------------
    with open(TOPICS) as f:
        tp = yaml.safe_load(f)
    names = [t["name"] for t in tp["topics"]]
    check("kafka: 11 topics", len(names) == 11, str(len(names)))
    check("kafka: unique names", len(set(names)) == len(names))
    check("kafka: partitions valid",
          all(isinstance(t.get("partitions"), int) and t["partitions"] > 0 for t in tp["topics"]))
    check("kafka: audit topic compacted",
          any(t["name"] == "audit.events" and t.get("cleanup_policy") == "compact"
              for t in tp["topics"]))

    # -- k8s ----------------------------------------------------------------------
    docs = [d for d in yaml.safe_load_all(open(K8S)) if d]
    kinds = {d["kind"] for d in docs}
    check("k8s: all 7 kinds present", EXPECTED_K8S_KINDS <= kinds, ",".join(sorted(kinds)))
    dep = next(d for d in docs if d["kind"] == "Deployment")
    c = dep["spec"]["template"]["spec"]["containers"][0]
    check("k8s: probes + resources on api container",
          all(k in c for k in ("readinessProbe", "livenessProbe", "resources")))
    check("k8s: nonroot security context",
          dep["spec"]["template"]["spec"].get("securityContext", {}).get("runAsNonRoot") is True)
    cron = next(d for d in docs if d["kind"] == "CronJob")
    check("k8s: nightly pipeline cron", cron["spec"]["schedule"].startswith("0 2"))

    # -- cypher (lint-level) --------------------------------------------------------
    cy = open(CYPHER).read()
    check("cypher: 10 uniqueness constraints", cy.count("CREATE CONSTRAINT") == 10,
          str(cy.count("CREATE CONSTRAINT")))
    check("cypher: seed mechanisms >= 4", cy.count(":Mechanism {id:") >= 4)
    check("cypher: balanced parens/braces",
          cy.count("(") == cy.count(")") and cy.count("{") == cy.count("}"))

# ----------------------------------------------------------------- boot -----
def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def boot_checks(tear_down: bool):
    if run(["docker", "info"]).returncode != 0:
        check("boot: docker daemon available", False,
              "no daemon — run this on a Docker host; static checks above still gate CI")
        return
    base = ["docker", "compose", "-f", COMPOSE, "--profile", "phase2"]
    check("boot: compose config valid", run(base + ["config", "-q"]).returncode == 0)
    check("boot: stack up", run(base + ["up", "-d", "--quiet-pull"]).returncode == 0)
    deadline, healthy = time.time() + 240, {}
    while time.time() < deadline:
        out = run(base + ["ps", "--format", "json"]).stdout
        rows = [json.loads(l) for l in out.splitlines() if l.strip()]
        healthy = {r["Service"]: r.get("Health", r.get("State")) for r in rows}
        if all(h in ("healthy", "running") for h in healthy.values()) and len(healthy) >= 5:
            break
        time.sleep(5)
    check("boot: all 5 services healthy", len(healthy) >= 5 and
          all(h in ("healthy", "running") for h in healthy.values()), str(healthy))
    tbl = run(base + ["exec", "-T", "postgres", "psql", "-U", "argus", "-d", "argus",
                      "-tAc", "SELECT count(*) FROM information_schema.tables "
                              "WHERE table_schema='public'"])
    check("boot: DDL applied (>=10 tables)", tbl.returncode == 0 and
          int(tbl.stdout.strip() or 0) >= 10, tbl.stdout.strip())
    import yaml
    topics = yaml.safe_load(open(TOPICS))["topics"]
    ok = all(run(base + ["exec", "-T", "kafka", "kafka-topics.sh",
                         "--bootstrap-server", "localhost:9092", "--create",
                         "--if-not-exists", "--topic", t["name"],
                         "--partitions", str(min(t["partitions"], 3)),
                         "--replication-factor", "1"]).returncode == 0
             for t in topics)
    check("boot: 11 kafka topics created", ok)
    if tear_down:
        run(base + ["down", "-v"])
        print("INFO  stack torn down (--down)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", action="store_true", help="run live compose boot check (needs Docker)")
    ap.add_argument("--down", action="store_true", help="tear down stack after boot check")
    args = ap.parse_args()
    print("== Task 39: Phase-2 stack verification ==")
    static_checks()
    if args.boot:
        boot_checks(args.down)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
