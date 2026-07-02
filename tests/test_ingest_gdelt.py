"""Task 42 — GDELT worker tests, fixture-driven (no live feed dependency).
Builds a synthetic GDELT v2 export (61 tab-separated cols) incl. a duplicate ID,
a geo-less row, and a malformed row; verifies parse, normalize, dedup, idempotency.
"""
import io, os, sys, time, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import reset_settings_cache
from services.ingest_common.sink import RawEventSink
from services.ingest_gdelt import worker


def gdelt_row(eid: str, day="20260610", a1="IRAN", a2="ISRAEL", code="190",
              root="19", quad="4", goldstein="-10.0", nsources="12",
              tone="-8.2", lat="26.5", lon="56.2", cc="IR",
              url="https://example.org/article") -> str:
    row = [""] * worker.N_COLS
    row[0], row[1] = eid, day
    row[6], row[16] = a1, a2
    row[26], row[28], row[29], row[30] = code, root, quad, goldstein
    row[32], row[34] = nsources, tone
    row[53], row[56], row[57] = cc, lat, lon
    row[60] = url
    return "\t".join(row)


@pytest.fixture
def fixture_zip(tmp_path):
    rows = [
        gdelt_row("900000001"),                                       # conflict, Hormuz area
        gdelt_row("900000002", a1="USA", a2="IRAN", code="040", root="04",
                  quad="1", goldstein="3.0", nsources="4", lat="38.9", lon="-77.0", cc="US"),
        gdelt_row("900000001"),                                       # duplicate ID
        gdelt_row("900000003", lat="", lon=""),                       # geo-less
        "short\trow",                                                 # malformed
        gdelt_row("900000004", day="banana"),                         # bad date
    ]
    csv_bytes = ("\n".join(rows) + "\n").encode()
    zpath = tmp_path / "20260610.export.CSV.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("20260610.export.CSV", csv_bytes)
    return str(zpath)


@pytest.fixture
def sink(tmp_path, monkeypatch):
    """SQLite sink, scoped per-test (must NOT nuke DATABASE_URL process-wide:
    the CI postgres job relies on it for the other test modules)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "copilot.db"))
    reset_settings_cache()
    s = RawEventSink(sqlite_path=str(tmp_path / "ingest.db"))
    yield s
    s.close()
    reset_settings_cache()


def test_parse_normalizes_and_filters(fixture_zip):
    events, q = worker.parse_export(worker.read_batch(fixture_zip))
    assert q["rows_bad"] == 2 and q["rows_no_geo"] == 1
    assert len(events) == 4                                   # dup still parsed; dedup at sink
    e = events[0]
    assert e["source"] == "gdelt" and e["source_id"] == "900000001"
    assert e["event_type"] == "fight"                         # CAMEO root 19
    assert e["actors"]["a1"] == "IRAN" and e["actors"]["country"] == "IR"
    assert e["magnitude"] == -10.0
    assert e["confidence"] == 1.0                             # 12 sources -> capped
    assert e["h3_cell"] and e["payload"]["url"].startswith("https://")
    assert events[1]["event_type"] == "consult" and events[1]["confidence"] == 0.4
    assert events[3]["h3_cell"] is None                       # geo-less kept, cell None


def test_ingest_lands_and_dedups(fixture_zip, sink):
    res = worker.ingest(fixture_zip, sink)
    assert res["received"] == 4 and res["inserted"] == 3 and res["duplicates"] == 1
    assert sink.count("gdelt") == 3
    again = worker.ingest(fixture_zip, sink)                  # idempotent re-run
    assert again["inserted"] == 0 and sink.count("gdelt") == 3
    smp = sink.sample("gdelt", 3)
    assert {s["source_id"] for s in smp} == {"900000001", "900000002", "900000003"}


def test_cell_fallback_grid():
    c = worker.cell_for(26.34, 56.18)
    assert c and (c.startswith("g5:") or len(c) == 15)        # grid fallback or real H3
    assert worker.cell_for(None, 12.0) is None


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="PG sink leg needs DATABASE_URL")
def test_sink_pg_leg():
    """Exercise the PostgreSQL insert path of RawEventSink (CI postgres job)."""
    from services.copilot.store_pg import PgStore
    reset_settings_cache()
    PgStore().close()                                  # ensure 001_init schema applied
    s = RawEventSink()
    assert s.backend == "postgres"
    eid = f"t42-{int(time.time()*1000)}"
    res = s.insert_many([{"source": "gdelt", "source_id": eid, "event_type": "fight",
                          "actors": {"a1": "X"}, "h3_cell": "g5:26.5,56.0",
                          "occurred_at": time.time(), "magnitude": -7.5,
                          "confidence": 0.6, "payload": {"test": True}}])
    assert res["inserted"] == 1
    dup = s.insert_many([{"source": "gdelt", "source_id": eid, "payload": {}}])
    assert dup["inserted"] == 0                        # ON CONFLICT DO NOTHING
    s.close()


def test_csv_plain_and_bytes_paths(fixture_zip, tmp_path):
    csv_path = tmp_path / "plain.csv"
    csv_path.write_text(gdelt_row("900000009") + "\n")
    events, _ = worker.parse_export(worker.read_batch(str(csv_path)))
    assert events[0]["source_id"] == "900000009"
    raw = open(fixture_zip, "rb").read()                      # zip bytes (live-mode shape)
    events2, _ = worker.parse_export(worker.read_batch(raw))
    assert len(events2) == 4
