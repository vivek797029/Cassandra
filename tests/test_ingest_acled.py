"""Task 44 — ACLED worker tests, fixture-driven (JSON + CSV drops, no live API)."""
import csv, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import reset_settings_cache
from services.ingest_common.sink import RawEventSink
from services.ingest_acled import worker


def rec(eid="IRN12345", date="2026-06-07", etype="Battles", sub="Armed clash",
        a1="Military Forces of Iran", a2="Military Forces of Israel",
        country="Iran", lat="35.69", lon="51.42", geo=1, tprec=1,
        fat="3", source="Reuters", notes="Exchange of strikes near Tehran."):
    return {"event_id_cnty": eid, "event_date": date, "event_type": etype,
            "sub_event_type": sub, "actor1": a1, "actor2": a2, "country": country,
            "admin1": "Tehran", "latitude": lat, "longitude": lon,
            "geo_precision": geo, "time_precision": tprec, "fatalities": fat,
            "source": source, "notes": notes}


FIXTURE = [
    rec(),                                                        # battle, precise
    rec(eid="EGY00001", date="2026-06-05", etype="Protests", sub="Peaceful protest",
        a1="Protesters (Egypt)", a2="", country="Egypt", lat="30.04", lon="31.24",
        geo=2, tprec=2, fat="0"),
    rec(eid="IRN12345"),                                          # duplicate id
    rec(eid="YEM00009", etype="Explosions/Remote violence", geo=3, tprec=1,
        lat="", lon="", fat="12"),                                # geo-less
    rec(eid="", date="2026-06-01"),                               # missing id -> bad
    rec(eid="SDN00007", date="June 1st"),                         # bad date -> bad
]


@pytest.fixture
def sink(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    reset_settings_cache()
    s = RawEventSink(sqlite_path=str(tmp_path / "i.db"))
    yield s
    s.close()
    reset_settings_cache()


def test_parse_normalizes(sink):
    events, q = worker.parse_records(FIXTURE)
    assert q["rows_bad"] == 2 and q["rows_no_geo"] == 1 and len(events) == 4
    e = events[0]
    assert e["source"] == "acled" and e["event_type"] == "battles"
    assert e["magnitude"] == 3.0 and e["payload"]["magnitude_kind"] == "fatalities"
    assert e["confidence"] == 0.9                       # precision 1/1
    assert e["h3_cell"] is not None
    p = events[1]
    assert p["event_type"] == "protests" and p["magnitude"] == 0.0
    assert p["confidence"] == 0.6                       # precision 2/2
    x = events[3]
    assert x["event_type"] == "explosions_remote_violence"
    assert x["confidence"] == 0.35 and x["h3_cell"] is None   # worst geo precision


def test_ingest_dedups_and_idempotent(sink):
    res = worker.ingest(FIXTURE, sink)
    assert res["received"] == 4 and res["inserted"] == 3 and res["duplicates"] == 1
    assert res["db_dup_groups"] == 0
    again = worker.ingest(FIXTURE, sink)
    assert again["inserted"] == 0 and sink.count("acled") == 3


def test_json_and_csv_drops(tmp_path, sink):
    jpath = tmp_path / "drop.json"
    jpath.write_text(json.dumps({"data": FIXTURE[:2]}))
    assert len(worker.read_batch(str(jpath))) == 2
    cpath = tmp_path / "drop.csv"
    with open(cpath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(FIXTURE[0].keys()))
        w.writeheader()
        w.writerows(FIXTURE[:2])
    records = worker.read_batch(str(cpath))
    events, _ = worker.parse_records(records)
    assert {e["source_id"] for e in events} == {"IRN12345", "EGY00001"}
    res = worker.ingest(records, sink)
    assert res["inserted"] == 2


def test_live_mode_refuses_without_credentials(monkeypatch):
    for v in ("ACLED_KEY", "ACLED_EMAIL"):
        monkeypatch.delenv(v, raising=False)
    reset_settings_cache()
    with pytest.raises(RuntimeError, match="ACLED_KEY"):
        worker.fetch_api(days=7)
    reset_settings_cache()


def test_sources_coexist_in_raw_events(sink):
    from tests.test_ingest_gdelt import gdelt_row
    from services.ingest_gdelt import worker as gworker
    import io
    gevents, _ = gworker.parse_export(io.StringIO(gdelt_row("555001") + "\n"))
    sink.insert_many(gevents)
    worker.ingest(FIXTURE, sink)
    assert sink.count("gdelt") == 1 and sink.count("acled") == 3
    assert sink.count() == 4                            # shared table, disjoint sources
