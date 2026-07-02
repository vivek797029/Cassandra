"""Task 62 — background job runner + SSE streaming for long simulations.

POST /v1/jobs            {kind: 'counterfactual', ...}  -> {job_id}
GET  /v1/stream/{job_id}  text/event-stream:
    event: progress  data: {"done": 2, "total": 5, "pct": 40}
    event: result    data: {...counterfactual result...}
    event: error     data: {"error": "..."}

In-process runner (threads + per-job queue), bounded concurrency. Suits the
single-service Phase-2 deployment; Phase-3 swaps the runner for a worker pool
behind the same endpoints.
"""
from __future__ import annotations
import json, queue, threading, time, uuid

MAX_CONCURRENT = 2
_SEM = threading.Semaphore(MAX_CONCURRENT)
JOBS: dict[str, dict] = {}                       # job_id -> {status, queue, result}
JOB_TTL_S = 600


def _gc():
    now = time.time()
    for jid in [j for j, v in JOBS.items() if now - v["created"] > JOB_TTL_S]:
        JOBS.pop(jid, None)


def submit_counterfactual(engines, body: dict) -> str:
    """body: {interventions[], hazard_mods{}, targets[], horizon_quarters, n_paths, n_batches}"""
    _gc()
    jid = uuid.uuid4().hex[:12]
    q: queue.Queue = queue.Queue()
    JOBS[jid] = {"status": "queued", "queue": q, "result": None,
                 "created": time.time(), "kind": "counterfactual"}

    def work():
        with _SEM:
            JOBS[jid]["status"] = "running"
            try:
                def cb(done, total):
                    q.put(("progress", {"done": done, "total": total,
                                        "pct": round(100 * done / total)}))
                res = engines.counterfactual_chunked(
                    body.get("interventions", []), body.get("hazard_mods", {}),
                    body.get("targets") or ["ME_war_1y", "Brent_gt120_1y"],
                    int(body.get("horizon_quarters", 12)),
                    int(body.get("n_paths", 20000)),
                    int(body.get("n_batches", 5)), progress_cb=cb)
                JOBS[jid]["result"] = res
                JOBS[jid]["status"] = "done"
                q.put(("result", res))
            except Exception as ex:                                  # surfaced to stream
                JOBS[jid]["status"] = "error"
                q.put(("error", {"error": str(ex)[:300]}))
            q.put(("__end__", None))

    threading.Thread(target=work, daemon=True).start()
    return jid


def sse_events(job_id: str):
    """Generator of SSE frames for a job (replays nothing; live tail)."""
    job = JOBS.get(job_id)
    if job is None:
        yield "event: error\ndata: {\"error\": \"unknown job\"}\n\n"
        return
    if job["status"] == "done" and job["result"] is not None:        # late subscriber
        yield f"event: result\ndata: {json.dumps(job['result'], default=str)}\n\n"
        return
    q: queue.Queue = job["queue"]
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            kind, payload = q.get(timeout=15)
        except queue.Empty:
            yield ": keepalive\n\n"
            continue
        if kind == "__end__":
            return
        yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"
