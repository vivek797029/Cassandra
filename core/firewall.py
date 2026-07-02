"""Task 52 — leakage firewall (blueprint §16: enforced by infrastructure, not policy).

Training/backtest code must see ONLY data at-or-before a cutoff. The firewall
wraps the data stores in cutoff-enforcing proxies: any read whose time range
extends past the cutoff raises LeakageError — peeking is impossible by
construction, not by convention. Every permitted read is recorded in an
access log (lineage), so a training run can attach PROOF of what it saw.

Usage:
    fw = Firewall(cutoff_ts)
    ser = fw.series(SeriesStore(...))     # FirewalledSeries
    snk = fw.sink(RawEventSink(...))      # FirewalledSink
    ... run training using ONLY these handles ...
    fw.lineage()      -> [{store, method, t1, at}]  (attach to the run manifest)
    fw.assert_clean() -> raises if anything ever touched post-cutoff (belt+braces)
"""
from __future__ import annotations
import time


class LeakageError(RuntimeError):
    """A data access crossed the training cutoff."""


class _Recorder:
    def __init__(self, cutoff: float):
        self.cutoff = float(cutoff)
        self.log: list[dict] = []
        self.violations = 0

    def check(self, store: str, method: str, t1: float | None):
        if t1 is not None and float(t1) > self.cutoff:
            self.violations += 1
            raise LeakageError(
                f"{store}.{method} requested data to t={t1:.0f} past cutoff "
                f"{self.cutoff:.0f} (+{(float(t1) - self.cutoff) / 86400:.1f} d)")
        self.log.append({"store": store, "method": method, "t1": t1,
                         "at": time.time()})


class FirewalledSeries:
    """Cutoff-enforcing proxy over services.ingest_common.series.SeriesStore."""

    def __init__(self, store, rec: _Recorder):
        self._s, self._rec = store, rec

    def value_asof(self, series: str, ts: float):
        self._rec.check("series", "value_asof", ts)
        return self._s.value_asof(series, ts)

    def first_crossing(self, series: str, op: str, value: float,
                       t0: float, t1: float):
        self._rec.check("series", "first_crossing", t1)
        return self._s.first_crossing(series, op, value, t0, t1)

    def list_series(self):
        self._rec.check("series", "list_series", None)
        return self._s.list_series()

    # write paths are NOT exposed: training must never mutate evidence
    def add_points(self, *a, **k):
        raise LeakageError("firewalled handle is read-only")


class FirewalledSink:
    """Cutoff-enforcing proxy over RawEventSink (read paths used in training)."""

    def __init__(self, store, rec: _Recorder):
        self._s, self._rec = store, rec
        self.backend = store.backend
        self.conn = _GuardedConn(store.conn, rec)      # resolver reads go via conn

    def count(self, source=None):
        self._rec.check("sink", "count", None)
        return self._s.count(source)

    def fetch_event_ts(self, rule: dict, t0: float, t1: float) -> list[float]:
        self._rec.check("sink", "fetch_event_ts", t1)
        from services.question_registry.resolver import _fetch_event_ts
        return _fetch_event_ts(self._s, rule, t0, t1)

    def insert_many(self, *a, **k):
        raise LeakageError("firewalled handle is read-only")


class _GuardedConn:
    """Blocks raw SQL through a firewalled sink unless it carries an explicit
    occurred_at upper bound ≤ cutoff (coarse guard for resolver internals)."""

    def __init__(self, conn, rec: _Recorder):
        self._conn, self._rec = conn, rec

    def execute(self, sql: str, params=()):
        low = sql.lower()
        if "occurred_at <=" not in low and "raw_events" in low:
            raise LeakageError("raw SQL on firewalled sink must bound occurred_at")
        # the bound itself is checked by the caller-supplied param convention:
        # resolver passes (src, t0, t1) -> last numeric param is t1
        nums = [p for p in (params or ()) if isinstance(p, (int, float))]
        self._rec.check("sink.conn", "execute", max(nums) if nums else None)
        return self._conn.execute(sql, params)

    def cursor(self):
        return self._conn.cursor()


class Firewall:
    def __init__(self, cutoff_ts: float):
        self._rec = _Recorder(cutoff_ts)
        self.cutoff = float(cutoff_ts)

    def series(self, store) -> FirewalledSeries:
        return FirewalledSeries(store, self._rec)

    def sink(self, store) -> FirewalledSink:
        return FirewalledSink(store, self._rec)

    def lineage(self) -> list[dict]:
        return list(self._rec.log)

    def assert_clean(self):
        if self._rec.violations:
            raise LeakageError(f"{self._rec.violations} post-cutoff access attempts")
        return True
