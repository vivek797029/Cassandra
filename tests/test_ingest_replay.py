"""Task 43 — replay quality-gate tests: 3 overlapping batches, gates verified both ways."""
import os, sys, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import reset_settings_cache
from services.ingest_common.sink import RawEventSink
from services.ingest_gdelt import replay
from tests.test_ingest_gdelt import gdelt_row


def make_batch(tmp_path, name: str, rows: list[str]) -> str:
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(name.replace(".zip", ""), "\n".join(rows) + "\n")
    return str(z)


@pytest.fixture
def sink(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    reset_settings_cache()
    s = RawEventSink(sqlite_path=str(tmp_path / "i.db"))
    yield s
    s.close()
    reset_settings_cache()


def test_replay_overlapping_batches_pass_gates(tmp_path, sink):
    b1 = make_batch(tmp_path, "b1.export.CSV.zip",
                    [gdelt_row(f"7000{i}") for i in range(10)])
    b2 = make_batch(tmp_path, "b2.export.CSV.zip",                  # 50% overlap with b1
                    [gdelt_row(f"7000{i}") for i in range(5, 15)])
    b3 = make_batch(tmp_path, "b3.export.CSV.zip",                  # disjoint + 1 geo-less
                    [gdelt_row(f"8000{i}") for i in range(4)] +
                    [gdelt_row("80009", lat="", lon="")])
    rep = replay.replay([b1, b2, b3], sink)
    assert rep["totals"]["received"] == 25 and rep["totals"]["inserted"] == 20
    assert rep["incoming_dup_rate"] == 0.2                          # 5/25 overlap absorbed
    assert rep["db_rows"] == 20 and rep["db_dup_groups"] == 0
    assert rep["db_null_id_rows"] == 0
    assert rep["geo_coverage"] == 0.95                              # 19/20 geocoded
    assert rep["bad_row_rate"] == 0.0
    assert rep["event_type_dist"]["fight"] == 25
    assert rep["passed"] is True and all(rep["gates"].values())


def test_replay_gate_fails_on_garbage_feed(tmp_path, sink):
    bad = make_batch(tmp_path, "bad.export.CSV.zip",
                     [gdelt_row("90001"), "garbage\trow", "another\tbad",
                      gdelt_row("90002", day="notaday")])
    rep = replay.replay([bad], sink)
    assert rep["bad_row_rate"] == 0.75                              # 3 of 4 rows bad
    assert rep["gates"]["bad_row_rate"] is False
    assert rep["passed"] is False


def test_replay_idempotent_second_pass(tmp_path, sink):
    b = make_batch(tmp_path, "x.export.CSV.zip", [gdelt_row(f"611{i}") for i in range(6)])
    r1 = replay.replay([b], sink)
    r2 = replay.replay([b], sink)                                   # full re-replay
    assert r1["totals"]["inserted"] == 6 and r2["totals"]["inserted"] == 0
    assert r2["incoming_dup_rate"] == 1.0
    assert r2["db_rows"] == 6 and r2["db_dup_groups"] == 0 and r2["gates"]["dedup_integrity"]
