"""Task 80 — structured JSON logging + request-id propagation. Logs are valid
JSON; an inbound X-Request-ID is honored and echoed; the id propagates to every
log emitted during the request (end-to-end trace)."""
import os, sys, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/logging_test.db")

from fastapi.testclient import TestClient
from services.copilot import logging_setup
from services.copilot.main import app


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
        self.addFilter(logging_setup.RequestIdFilter())   # inject request_id like the real handler

    def emit(self, record):
        self.records.append(record)


def _with_capture():
    cap = Capture()
    logging.getLogger().addHandler(cap)
    return cap


# --------------------------------------------------------------- unit -------
def test_json_formatter_is_valid_json_with_extras():
    logging_setup.set_request_id("rid-xyz")
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    rec.path, rec.status = "/v1/ask", 200
    logging_setup.RequestIdFilter().filter(rec)
    out = json.loads(logging_setup.JsonFormatter().format(rec))
    assert out["msg"] == "hello" and out["level"] == "INFO"
    assert out["request_id"] == "rid-xyz" and out["path"] == "/v1/ask" and out["status"] == 200
    assert "ts" in out and out["ts"].endswith("Z")
    logging_setup.set_request_id("-")


# ------------------------------------------------------- integration --------
def test_inbound_request_id_echoed_and_logged():
    cap = _with_capture()
    try:
        r = TestClient(app).get("/healthz", headers={"X-Request-ID": "trace-abc"})
        assert r.headers["X-Request-ID"] == "trace-abc"
        reqs = [x for x in cap.records if x.getMessage() == "request"]
        assert reqs, "no access log line emitted"
        last = reqs[-1]
        assert last.request_id == "trace-abc"
        assert last.method == "GET" and last.path == "/healthz" and last.status == 200
        assert isinstance(last.latency_ms, int)
    finally:
        logging.getLogger().removeHandler(cap)


def test_request_id_generated_when_absent():
    cap = _with_capture()
    try:
        r = TestClient(app).get("/healthz")
        rid = r.headers["X-Request-ID"]
        assert len(rid) == 16
        reqs = [x for x in cap.records if x.getMessage() == "request"]
        assert reqs[-1].request_id == rid
    finally:
        logging.getLogger().removeHandler(cap)


def test_request_id_propagates_to_any_logger():
    cap = _with_capture()
    try:
        logging_setup.set_request_id("propagated-1")
        logging.getLogger("some.library").warning("deep log line")
        rec = [x for x in cap.records if x.getMessage() == "deep log line"][-1]
        assert rec.request_id == "propagated-1"        # end-to-end correlation
    finally:
        logging.getLogger().removeHandler(cap)
        logging_setup.set_request_id("-")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
