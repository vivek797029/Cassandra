"""Task 90 — DR active-active manifests are valid and define streaming replication
(primary + standby) with a documented failover drill at <15min RPO."""
import os, yaml

DR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "deploy", "k8s", "dr")


def test_dr_manifests_parse_and_define_primary_and_standby():
    text = open(os.path.join(DR, "postgres-dr.yaml"), encoding="utf-8").read()
    docs = [d for d in yaml.safe_load_all(text) if d]
    kinds = [(d.get("kind"), d.get("metadata", {}).get("name")) for d in docs]
    names = {n for _, n in kinds}
    assert ("StatefulSet", "pg-primary") in kinds
    assert ("StatefulSet", "pg-standby") in kinds
    assert "pg-primary" in names and "pg-standby" in names      # Services too
    # streaming replication is actually configured
    assert "wal_level = replica" in text
    assert "max_wal_senders" in text
    assert "primary_conninfo" in text and "standby.signal" in text
    assert "pg_basebackup" in text                              # standby clones the primary


def test_failover_runbook_documents_rpo_and_drill():
    t = open(os.path.join(DR, "README.md"), encoding="utf-8").read().lower()
    assert "active-active" in t
    assert "rpo" in t and "15 min" in t                         # the target
    assert "failover drill" in t and "promote" in t
    assert "manifest sync" in t                                 # GitOps reconcile both clusters


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
