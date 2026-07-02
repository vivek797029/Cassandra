"""Task 80 — structured JSON logging + request-id propagation (Loki-ready).

Every log line is one JSON object on stdout (Loki/promtail parse it directly).
A per-request id lives in a ContextVar so EVERY log emitted while handling a
request — from middleware, endpoint, or any library logger — carries the same
`request_id`, letting you trace a request end-to-end. The id is taken from an
inbound `X-Request-ID` header (gateway/proxy) or generated, and echoed back.
"""
from __future__ import annotations
import json, logging, sys, time, uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# LogRecord built-ins we don't want to duplicate into the JSON body.
_STD = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    "request_id", "message",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for k, v in record.__dict__.items():           # structured extras (method/path/…)
            if k not in _STD and not k.startswith("_"):
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


_configured = False


def configure_logging(level: str | int = "INFO") -> None:
    """Idempotently route the root logger to stdout as JSON with request-id."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    _configured = True


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(rid: str) -> str:
    request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    return request_id_var.get()


access_logger = logging.getLogger("argus.access")
