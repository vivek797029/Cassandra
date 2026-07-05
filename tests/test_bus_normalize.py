"""Tasks 45+46 — event bus, producers, and normalize consumer (FileBus end-to-end)."""
import io, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import reset_settings_cache
from services.ingest_common.bus import FileBus, get_bus, reset_bus, RAW_TOPICS, TOPIC_NORMALIZED
from services.ingest_common.sink import RawEventSink
from services.ingest_common import normalize
from services.ingest_gdelt import worker as gworker
from services.ingest_acled import worker as aworker
from tests.test_ingest_gdelt import gdelt_row
from tests.test_ingest_acled import FIXTURE as ACLED_FIXTURE


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ARGUS_KAFKA_BROKERS", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    reset_settings_cache(); reset_bus()
    b = FileBus(root=str(tmp_path / "bus"))
    s = RawEventSink(sqlite_path=str(tmp_path / "i.db"))
    yield b, s
    s.close(); reset_settings_cache(); reset_bus()


def test_factory_selects_filebus_without_brokers(env, monkeypatch):
    assert get_bus().backend == "file"
    monkeypatch.setenv("ARGUS_KAFKA_BROKERS", "kafka:9092")
    reset_bus()
    assert get_bus().backend == "kafka"          # selection only; no connection made
    reset_bus()


def test_envelope_and_spool_roundtrip(env):
    b, _ = env
    n = b.publish(RAW_TOPICS["gdelt"], [{"source_id": "x1", "a": 1}], producer="t")
    assert n == 1 and b.depth(RAW_TOPICS["gdelt"]) == 1
    env0 = b.read(RAW_TOPICS["gdelt"])[0]
    assert env0["topic"] == "ingest.raw.gdelt" and env0["key"] == "x1"
    assert env0["producer"] == "t" and abs(env0["ts"] - time.time()) < 5
    assert env0["payload"]["a"] == 1


def test_workers_publish_to_raw_topics(env):
    b, s = env
    res_g = gworker.ingest(io.StringIO(gdelt_row("450001") + "\n" + gdelt_row("450002") + "\n"),
                           s, bus=b)
    res_a = aworker.ingest(ACLED_FIXTURE, s, bus=b)
    assert res_g["published"] == 2 and b.depth(RAW_TOPICS["gdelt"]) == 2
    assert res_a["published"] == 4 and b.depth(RAW_TOPICS["acled"]) == 4
    assert res_g["inserted"] == 2                # dual-write still lands in sink


def test_normalize_consumer_end_to_end(env):
    b, s = env
    gworker.ingest(io.StringIO(gdelt_row("460001") + "\n"), s, bus=b)
    aworker.ingest(ACLED_FIXTURE, s, bus=b)
    # poison message: invalid confidence
    b.publish(RAW_TOPICS["gdelt"], [{"source": "gdelt", "source_id": "bad1",
                                     "event_type": "fight", "occurred_at": time.time(),
                                     "confidence": 7.7}], producer="t")
    stats = normalize.consume_once(bus=b, sink=s)
    g, a = stats["ingest.raw.gdelt"], stats["ingest.raw.acled"]
    assert g["read"] == 2 and g["valid"] == 1 and g["invalid"] == 1
    assert g["invalid_reasons"] == {"confidence:out_of_range": 1}
    assert a["read"] == 4 and a["valid"] == 4
    assert g["inserted"] == 0 and a["inserted"] == 0          # dual-write dedup absorbed
    assert g["max_lag_s"] < 60 and a["max_lag_s"] < 60        # Task-46 lag gate (<5 min)
    assert b.depth(TOPIC_NORMALIZED) == 5                     # 1 gdelt + 4 acled enriched
    norm = b.read(TOPIC_NORMALIZED)
    domains = {e["payload"]["domain"] for e in norm}
    assert domains <= {"security", "social", "political", "economic", "environmental"}
    assert norm[0]["payload"]["domain"] == "security"          # fight -> security


def test_consumer_checkpoint_no_rework(env):
    b, s = env
    gworker.ingest(io.StringIO(gdelt_row("470001") + "\n"), s, bus=b)
    s1 = normalize.consume_once(bus=b, sink=s)
    s2 = normalize.consume_once(bus=b, sink=s)                # nothing new
    assert s1["ingest.raw.gdelt"]["read"] == 1
    assert s2["ingest.raw.gdelt"]["read"] == 0
    gworker.ingest(io.StringIO(gdelt_row("470002") + "\n"), s, bus=b)
    s3 = normalize.consume_once(bus=b, sink=s)                # only the new message
    assert s3["ingest.raw.gdelt"]["read"] == 1


def test_domain_enrichment_map():
    assert normalize.enrich({"event_type": "protests"})["domain"] == "social"
    assert normalize.enrich({"event_type": "battles"})["domain"] == "security"
    assert normalize.enrich({"event_type": "provide_aid"})["domain"] == "economic"
    assert normalize.enrich({"event_type": "mystery"})["domain"] == "political"
