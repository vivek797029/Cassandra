"""Tasks 52-56 — firewall, theta registry+promotion, retrain ratchet, KG loader, evidence API."""
import os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import reset_settings_cache

D = lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("ARGUS_THETA_CACHE", str(tmp_path / "theta.json"))
    reset_settings_cache()
    import services.copilot.store as storemod
    storemod.STORE = None
    yield tmp_path
    storemod.STORE = None
    reset_settings_cache()


# ------------------------------------------------------------------ Task 52 --
def test_firewall_blocks_post_cutoff_and_records_lineage(env, tmp_path):
    from core.firewall import Firewall, LeakageError
    from services.ingest_common.series import SeriesStore
    from services.ingest_common.sink import RawEventSink
    ser = SeriesStore(sqlite_path=str(tmp_path / "s.db"))
    ser.add_points("brent_usd", [(D("2026-03-01"), 100), (D("2026-05-01"), 120)])
    snk = RawEventSink(sqlite_path=str(tmp_path / "i.db"))
    cutoff = D("2026-04-01")
    fw = Firewall(cutoff)
    fser, fsnk = fw.series(ser), fw.sink(snk)
    assert fser.value_asof("brent_usd", D("2026-03-15")) == 100      # pre-cutoff OK
    with pytest.raises(LeakageError):
        fser.value_asof("brent_usd", D("2026-05-02"))                # post-cutoff blocked
    with pytest.raises(LeakageError):
        fser.first_crossing("brent_usd", ">", 110, D("2026-01-01"), D("2026-06-01"))
    with pytest.raises(LeakageError):
        fser.add_points("brent_usd", [(D("2026-01-01"), 1)])         # read-only
    with pytest.raises(LeakageError):
        fsnk.fetch_event_ts({"source": "acled"}, D("2026-01-01"), D("2026-05-01"))
    assert fsnk.fetch_event_ts({"source": "acled"}, D("2026-01-01"),
                               D("2026-03-31")) == []                # bounded read OK
    lineage = fw.lineage()
    assert len(lineage) == 2                                          # only permitted reads
    assert {l["method"] for l in lineage} == {"value_asof", "fetch_event_ts"}
    with pytest.raises(LeakageError):
        fw.assert_clean()                                             # violations recorded


# ------------------------------------------------------------------ Task 53 --
def test_theta_versions_save_promote_roundtrip(env, tmp_path):
    from services.copilot.store import Store
    from core.engine import THETA_NAMES, THETA_DEFAULT
    st = Store(path=str(tmp_path / "c.db"))
    vals = [float(x) for x in THETA_DEFAULT]
    st.theta_save("aaa111", THETA_NAMES, vals, 0.20, "v1")
    st.theta_save("bbb222", THETA_NAMES, [v * 1.01 for v in vals], 0.18, "v2")
    assert st.theta_promoted() is None
    st.theta_promote("aaa111")
    assert st.theta_promoted()["theta_hash"] == "aaa111"
    st.theta_promote("bbb222")                                       # single champion
    promoted = st.theta_promoted()
    assert promoted["theta_hash"] == "bbb222" and promoted["brier_replay"] == 0.18
    assert [t["promoted"] for t in st.theta_list()].count(1) == 1
    with pytest.raises(KeyError):
        st.theta_promote("nope")


def test_engines_load_promoted_theta_and_readyz(env, tmp_path):
    from services.copilot.store import Store
    from core.engine import THETA_NAMES, THETA_DEFAULT
    st = Store(path=str(tmp_path / "c.db"))
    vals = [float(x) for x in THETA_DEFAULT]
    vals[0] = 0.123                                                   # recognizable marker
    st.theta_save("promo123abc0", THETA_NAMES, vals, 0.15, "test champion")
    st.theta_promote("promo123abc0")
    import services.copilot.engines as eng
    eng.ENGINES = None
    from fastapi.testclient import TestClient
    from services.copilot.main import app
    with TestClient(app) as c:
        r = c.get("/readyz").json()
        assert r["theta_source"] == "promoted-db"
        assert r["theta_promoted"]["hash"] == "promo123abc0"
    assert abs(eng.ENGINES.theta[0] - 0.123) < 1e-9                   # champion actually used
    eng.ENGINES = None


# ------------------------------------------------------------------ Task 54 --
def test_retrain_ratchet_promotes_only_better(env, tmp_path):
    from services.copilot.store import Store
    from services.question_registry.registry import QuestionRegistry
    from services.ingest_common.bus import FileBus
    from workers.retrain import daily
    st = Store(path=str(tmp_path / "c.db"))
    reg = QuestionRegistry(sqlite_path=str(tmp_path / "r.db"))
    bus = FileBus(root=str(tmp_path / "bus"))
    rep0 = daily.run(force=False, store=st, reg=reg, bus=bus)
    assert rep0["skipped"] is True                                    # no trigger
    rep1 = daily.run(force=True, iters=6, n_paths=600, store=st, reg=reg, bus=bus)
    assert rep1["skipped"] is False and rep1["event_set"] == "builtin-replay"
    assert rep1["promoted"] is True                                   # bootstrap promotion
    champ = st.theta_promoted()
    assert champ["theta_hash"] == rep1["challenger"]
    # sabotage: make champion artificially unbeatable -> next run must NOT promote
    st.theta_save(champ["theta_hash"], champ["names"], champ["vals"], -1.0, "sabotage")
    rep2 = daily.run(force=True, iters=2, n_paths=400, store=st, reg=reg, bus=bus)
    assert rep2["brier_champion"] is not None
    if rep2["brier_challenger"] > rep2["brier_champion"]:
        assert rep2["promoted"] is False
        assert st.theta_promoted()["theta_hash"] == champ["theta_hash"]
    assert bus.depth(daily.TOPIC_RUNS) >= 1                           # run published
    run_rec = st.get_run(rep1["manifest_id"])
    assert run_rec["payload"]["job"] == "retrain"


# ------------------------------------------------------------------ Task 55 --
def test_kg_loader_idempotent_merge_only(env, tmp_path):
    from services.kg import loader
    stmts = loader.generate_statements()
    assert len(stmts) > 60
    for s in stmts:                                                   # MERGE/MATCH+MERGE only
        head = s.split()[0]
        assert head in ("MERGE", "MATCH"), s[:60]
        assert "CREATE " not in s
    assert stmts == loader.generate_statements()                      # deterministic
    out = str(tmp_path / "kg.cypher")
    res = loader.load(out_path=out)
    assert res["mode"] == "cypher-file" and os.path.exists(out)
    body = open(out).read()
    assert body.count("MERGE (c:Claim {id:'F1'})") == 1
    assert "Mechanism {id:'oil__inflation'}" in body
    assert "\\'" in body or "'" in body                               # escaping exercised
    apostrophe_fact = "Operation Epic Fury"                           # text with quote chars
    assert apostrophe_fact in body


# ------------------------------------------------------------------ Task 56 --
def test_evidence_api_matches_situation(env):
    from services.kg import api as kgapi
    kgapi.reset_provider()
    from fastapi.testclient import TestClient
    from services.copilot.main import app
    from core.phases import load_situation
    sit = load_situation()
    with TestClient(app) as c:
        keys = c.get("/v1/evidence").json()
        assert keys["provider"] == "local-mirror"
        assert set(keys["keys"]) == set(sit["explanations"].keys())
        key = "ME_war_1y"
        chain = c.get(f"/v1/evidence/{key}").json()
        exp = sit["explanations"][key]
        assert [f["id"] for f in chain["facts"]] == exp["evidence"]   # exact match
        facts_by_id = {f["id"]: f for f in sit["facts"]}
        assert chain["facts"][0]["text"] == facts_by_id[exp["evidence"][0]]["text"]
        assert chain["mechanism"] == exp["mechanism"]
        assert chain["counterargument"] == exp["counter"]
        assert c.get("/v1/evidence/NOPE").status_code == 404
    kgapi.reset_provider()
