"""ARGUS Copilot API — FastAPI service.
Run:  uvicorn services.copilot.main:app --port 8000   (from repo root)
Env:  ARGUS_FAST=1 (default, ~5s startup) | ARGUS_DB | OLLAMA_URL (optional NLU assist)
"""
from __future__ import annotations
import os, sys, time, hmac, hashlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI, HTTPException, Response, Depends
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from services.gateway.deps import require_principal, require_clearance
from services.gateway.clearance import Principal
from services.gateway import classification, dlp
from services.llm import entail
from services.copilot import nlu, composer, degrade, telemetry, logging_setup

logging_setup.configure_logging()                  # Task 80: JSON logs + request-id
_log = logging_setup.access_logger
from services.copilot.config import get_settings
from services.copilot.engines import get_engines, QUESTION_TEXT
from services.copilot.store import get_store
from services.copilot.schemas import (AskRequest, AskResponse, CounterfactualRequest,
                                      Forecast, Explanation, CounterfactualResult,
                                      PolicyRecommendation, Analog, EarlyWarning,
                                      DissentRequest)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def _app_version() -> str:
    """Single source of truth: the repo VERSION file (Task 73)."""
    try:
        with open(os.path.join(_REPO_ROOT, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except Exception:
        return "0.0.0"

app = FastAPI(title="ARGUS Strategic Intelligence Copilot", version=_app_version(),
              description="Conversational copilot over the cassandra-core engines. "
                          "All numbers come from scored engines; the LLM (optional) only parses intents.")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _telemetry_mw(request, call_next):
    """Task 79: RED metrics per request, labelled by the matched route template
    (low cardinality)."""
    t0 = time.time()
    resp = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", None) or "unmatched"
    telemetry.record_request(request.method, path, resp.status_code, time.time() - t0)
    return resp


@app.middleware("http")
async def _request_id_mw(request, call_next):
    """Task 80: bind a request id (inbound X-Request-ID or generated) so every log
    line during this request is correlatable; echo it back. Outermost middleware."""
    rid = request.headers.get("X-Request-ID") or logging_setup.new_request_id()
    logging_setup.set_request_id(rid)
    t0 = time.time()
    resp = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    resp.headers["X-Request-ID"] = rid
    _log.info("request", extra={"method": request.method, "path": path,
                                "status": resp.status_code,
                                "latency_ms": int(1000 * (time.time() - t0))})
    return resp

STATIC = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "static")
T0 = time.time()

from services.question_registry.api import router as questions_router, get_registry
from services.kg.api import router as evidence_router
app.include_router(questions_router)
app.include_router(evidence_router)

@app.on_event("startup")
def _warm():
    get_engines(); get_store(); get_registry()   # registry seeds engine questions idempotently
    try:
        degrade.save_snapshot(get_engines())      # Task 70: capture last-known-good read snapshot
    except Exception:
        pass

# ---------------- Task 70: graceful degradation ----------------
def get_source(response: Response | None = None):
    """Return (read_source, degraded). Live engine when healthy; otherwise the
    last-known-good snapshot with degraded=True. Sets X-Argus-Degraded when stale.
    Raises 503 only if the engine is down AND no snapshot exists."""
    try:
        return get_engines(), False
    except Exception:
        snap = degrade.load_snapshot()
        if snap is None:
            raise HTTPException(503, "forecasting engine unavailable and no cached snapshot")
        if response is not None:
            response.headers["X-Argus-Degraded"] = "1"
        return degrade.SnapshotSource(snap), True

def _require_live():
    """For live-compute endpoints: real engine or an honest 503 (no fake cache)."""
    try:
        return get_engines()
    except Exception:
        raise HTTPException(503, "forecasting engine unavailable — live simulation paused (degraded mode)")

# ---------------- health ----------------
@app.get("/healthz")
def healthz():
    return {"status": "ok", "uptime_s": round(time.time() - T0, 1)}

@app.get("/readyz")
def readyz(response: Response):
    try:
        e = get_engines()
    except Exception:
        # Task 70: live engine down. Liveness (/healthz) stays ok; readiness reports
        # degraded so orchestrators see it, but the API can still serve cached reads.
        snap = degrade.load_snapshot()
        response.status_code = 503
        return {"status": "degraded", "degraded": True,
                "snapshot": degrade.staleness(snap) if snap else None,
                "serving": "cached snapshot" if snap else "none"}
    promoted = None
    try:
        promoted = get_store().theta_promoted()
    except Exception:
        pass
    return {"status": "ready", "degraded": False, "theta_hash": e.theta_hash,
            "startup_s": e.startup_s, "n_paths_cached": int(e.base_sim["N"]),
            "theta_source": getattr(e, "theta_source", "unknown"),
            "theta_promoted": ({"hash": promoted["theta_hash"],
                                "brier": promoted["brier_replay"]} if promoted else None)}

# ---------------- identity / authz (Task 74) ----------------
@app.get("/v1/whoami")
def whoami(principal: Principal = Depends(require_principal)):
    """The verified caller: subject, clearance level, scopes, persona. With auth
    disabled (dev) this returns the trusted-local principal."""
    return principal.to_dict()

@app.get("/v1/admin/ping")
def admin_ping(principal: Principal = Depends(require_clearance("SECRET"))):
    """Clearance-gated probe: requires SECRET (demonstrates the authz gate)."""
    return {"ok": True, "sub": principal.sub, "clearance": principal.clearance}

# theta promotion — dual-control sign-off + audit chain (Task 89); SECRET only
@app.post("/v1/admin/theta/request")
def theta_request(body: dict, principal: Principal = Depends(require_clearance("SECRET"))):
    from services.admin.promote import get_promotion_workflow
    return get_promotion_workflow().request(body["theta_hash"], principal.sub, body.get("reason", ""))

@app.post("/v1/admin/theta/approve")
def theta_approve(body: dict, principal: Principal = Depends(require_clearance("SECRET"))):
    from services.admin.promote import get_promotion_workflow, PromotionError
    try:
        return get_promotion_workflow().approve(body["theta_hash"], principal.sub)
    except PromotionError as e:
        raise HTTPException(409, str(e))

@app.post("/v1/admin/theta/promote")
def theta_promote_ep(body: dict, principal: Principal = Depends(require_clearance("SECRET"))):
    from services.admin.promote import get_promotion_workflow, PromotionError
    try:
        return get_promotion_workflow().promote(body["theta_hash"])
    except PromotionError as e:
        raise HTTPException(409, str(e))     # unsigned / under-approved theta rejected
    except KeyError:
        raise HTTPException(404, "unknown theta_hash")

# ---------------- copilot ----------------
@app.post("/v1/ask", response_model=AskResponse)
def ask(req: AskRequest, response: Response,
        principal: Principal = Depends(require_principal)):
    t0 = time.time()
    e, degraded = get_source(response)            # Task 70: live engine or cached snapshot
    s = get_store()
    sid = s.ensure_session(req.session_id, req.persona)
    s.log_message(sid, "user", req.text)
    p = nlu.parse(req.text)
    intent = p["intent"]
    objs: dict = {"forecasts": [], "manifest_id": ""}

    if degraded and intent in ("WHATIF", "POLICY"):
        # No honest cached answer for a simulation that never ran — say so plainly.
        md = (degrade.banner(e.snap) + "\n\n"
              "Live what-if and policy simulation is paused in degraded mode. "
              "Forecast, explanation, early-warning and status queries are still "
              "answered from the cached snapshot.")
        abstained = True
    else:
        if intent in ("FORECAST", "CAUSE", "EXPLAIN", "STATUS"):
            keys = p["keys"] or (list(QUESTION_TEXT)[:3] if intent == "STATUS" else [])
            objs["forecasts"] = [f for k in keys if (f := e.forecast(k))]
            if objs["forecasts"]:
                objs["manifest_id"] = objs["forecasts"][0]["manifest_id"]
            if keys:
                objs["explanation"] = e.explanation(keys[0])
            if intent == "STATUS":
                red = classification.redact_facts(e.facts(), principal)  # Task 75
                objs["facts"] = red["facts"]
                objs["redaction_notice"] = classification.redaction_notice(red)
                objs["_withheld_terms"] = red.get("withheld_texts", [])  # Task 91 DLP input
        elif intent == "WHATIF":
            if p["interventions"]:
                cf = e.counterfactual(p["interventions"], {}, p["keys"] or
                                      ["ME_war_1y", "Hormuz_closure_by_end2027", "Brent_gt120_1y"],
                                      p["horizon_quarters"])
                cf["request"] = {"do": {"interventions": p["interventions"], "hazard_mods": {}},
                                 "targets": p["keys"] or ["ME_war_1y"],
                                 "horizon_quarters": p["horizon_quarters"], "n_paths": 2000}
                objs["counterfactual"] = cf
                objs["manifest_id"] = cf["manifest_id"]
                s.record_run(cf["manifest_id"], "counterfactual", cf["request"], e.theta_hash, e.seed)
        elif intent == "POLICY":
            pol = e.policy(budget=p["budget"])
            objs["policy"] = pol
            objs["manifest_id"] = pol["manifest_id"]
            s.record_run(pol["manifest_id"], "policy", {"budget": p["budget"]}, e.theta_hash, e.seed)
        elif intent == "EWI" or intent == "VULNERABILITY":
            objs["early_warnings"] = e.ewi()
        elif intent == "ANALOG":
            objs["analogs"] = e.analogs(req.text)
        elif intent == "SCENARIOS":
            objs["scenarios"] = e.scenarios

        md, abstained = composer.compose(intent, p, objs, req.persona)
        if degraded:                               # stamp cached reads as stale
            md = degrade.banner(e.snap) + "\n\n" + md

    if not degraded and not abstained:               # Task 77: faithfulness gate
        if get_settings().entailment_enforce:
            md, _ = entail.enforce(md, objs)          # block unfaithful sentences
        else:
            entail.gate(md, objs)                     # audit-only (records metrics)

    _cfg = get_settings()                             # Task 91: DLP egress gate
    if _cfg.dlp_enforce:
        md, _ = dlp.enforce(md, canaries=_cfg.dlp_canary_list,
                            classified_terms=objs.get("_withheld_terms"))

    latency = int(1000 * (time.time() - t0))
    s.log_message(sid, "assistant", md, intent, objs.get("manifest_id", ""), latency)
    return AskResponse(
        session_id=sid, intent=intent, parse=p, answer_markdown=md,
        forecasts=[Forecast(**f) for f in objs.get("forecasts", [])],
        explanation=Explanation(**objs["explanation"]) if objs.get("explanation") else None,
        counterfactual=CounterfactualResult(**objs["counterfactual"]) if objs.get("counterfactual") else None,
        policy=PolicyRecommendation(**objs["policy"]) if objs.get("policy") else None,
        analogs=[Analog(**a) for a in objs.get("analogs", [])[:5]],
        early_warnings=[EarlyWarning(**w) for w in objs.get("early_warnings", [])],
        abstained=abstained, degraded=degraded,
        staleness=degrade.staleness(e.snap) if degraded else None,
        manifest_id=objs.get("manifest_id", ""), latency_ms=latency)

# ---------------- engine endpoints ----------------
@app.get("/v1/forecasts")
def forecasts(response: Response):
    src, _ = get_source(response)
    return src.all_forecasts()

@app.get("/v1/forecasts/{key}")
def forecast(key: str, response: Response):
    src, _ = get_source(response)
    f = src.forecast(key)
    if not f:
        raise HTTPException(404, f"unknown forecast key '{key}'")
    f = dict(f)
    f["dissents"] = get_store().dissents_for(key)     # Task 87: dissent travels with render
    return f

# ---------------- dissent / right-of-reply (Task 87) ----------------
@app.post("/v1/dissents")
def create_dissent(req: DissentRequest, principal: Principal = Depends(require_principal)):
    """File a signed dissent against a forecast. Signed by the verified principal;
    it then travels with that forecast for every future reader."""
    ts = time.time()
    sig = hmac.new(get_settings().jwt_secret.encode(),
                   f"{principal.sub}|{req.key}|{req.text}|{ts}".encode(),
                   hashlib.sha256).hexdigest()[:32]
    did = get_store().dissent_save(req.key, principal.sub, principal.clearance,
                                   req.text, sig, created_at=ts)
    return {"id": did, "key": req.key, "author": principal.sub,
            "clearance": principal.clearance, "signature": sig, "created_at": ts}

@app.get("/v1/dissents")
def list_dissents(key: str):
    return get_store().dissents_for(key)

@app.get("/v1/fans")
def fans(response: Response):
    src, _ = get_source(response)
    return src.fans

@app.get("/v1/explanations/{key}")
def explanation(key: str, response: Response):
    src, _ = get_source(response)
    ex = src.explanation(key)
    if not ex:
        raise HTTPException(404, f"no explanation for '{key}'")
    return ex

@app.post("/v1/counterfactual")
def counterfactual(req: CounterfactualRequest):
    e, s = _require_live(), get_store()           # live-compute only (503 if degraded)
    cf = e.counterfactual(req.do.interventions, req.do.hazard_mods,
                          req.targets, req.horizon_quarters, req.n_paths)
    cf["request"] = req.model_dump()
    s.record_run(cf["manifest_id"], "counterfactual", cf["request"], e.theta_hash, e.seed)
    return cf

@app.post("/v1/policy/optimize")
def policy(budget: float = 8.0):
    e, s = _require_live(), get_store()           # live-compute only (503 if degraded)
    pol = e.policy(budget=budget)
    s.record_run(pol["manifest_id"], "policy", {"budget": budget}, e.theta_hash, e.seed)
    return pol

@app.post("/v1/jobs")
def create_job(body: dict):
    """Task 62: submit a long-running simulation; stream progress at /v1/stream/{id}."""
    from services.copilot import jobs
    kind = body.get("kind", "counterfactual")
    if kind != "counterfactual":
        raise HTTPException(422, f"unsupported job kind '{kind}'")
    jid = jobs.submit_counterfactual(_require_live(), body)   # live sim only (503 if degraded)
    return {"job_id": jid, "stream": f"/v1/stream/{jid}"}

@app.get("/v1/jobs/{job_id}")
def job_status(job_id: str):
    from services.copilot.jobs import JOBS
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return {"job_id": job_id, "status": j["status"], "kind": j["kind"],
            "result": j["result"] if j["status"] == "done" else None}

@app.get("/v1/stream/{job_id}")
def stream(job_id: str):
    from services.copilot.jobs import sse_events
    return StreamingResponse(sse_events(job_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})

@app.get("/v1/ewi/alerts")
def ewi_alerts(since: float = 0.0, limit: int = 50):
    """Task 64: recent early-warning alerts from the bus (ewi.alerts)."""
    from services.ingest_common.bus import get_bus
    from services.ewi.watch import TOPIC_ALERTS
    envs = get_bus().read(TOPIC_ALERTS)
    alerts = [e["payload"] for e in envs if float(e.get("ts") or 0) > since]
    return {"alerts": alerts[-limit:], "served_at": time.time()}

@app.get("/v1/analogs")
def analogs(response: Response, query: str = ""):
    src, _ = get_source(response)
    return src.analogs(query)

@app.get("/v1/ewi")
def ewi(response: Response):
    src, _ = get_source(response)
    return src.ewi()

@app.get("/v1/scenarios")
def scenarios(response: Response):
    src, _ = get_source(response)
    return src.scenarios

@app.get("/v1/redteam")
def redteam():
    return _require_live().redteam               # red-team summary isn't snapshotted

@app.get("/v1/facts")
def facts(response: Response, principal: Principal = Depends(require_principal)):
    src, _ = get_source(response)
    red = classification.redact_facts(src.facts(), principal)   # Task 75: clearance filter
    response.headers["X-Argus-Redacted"] = str(red["hidden"])
    response.headers["X-Argus-Cells-Masked"] = str(red["cells_masked"])
    return red["facts"]

@app.get("/v1/mechanisms")
def mechanisms():
    """Task 57: mechanism cards + the id-status gate report on the LIVE theta."""
    from services.kg.gate import mechanisms_view, gate_theta
    view = mechanisms_view()
    e = _require_live()                           # needs the live theta vector
    _, live_report = gate_theta(e.theta)
    view["gate_report_on_live_theta"] = live_report
    view["theta_hash"] = e.theta_hash
    return view

@app.get("/v1/calibration")
def calibration():
    """Task 60: track-record report — Brier/log/BSS/ECE, strata, reliability bins.
    Served from the last scoring run (output/calibration.json) or computed live."""
    import json as _json
    from workers.score import OUT_JSON, score
    from services.question_registry.registry import QuestionRegistry
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON) as f:
            rep = _json.load(f)
        rep["source"] = "last-scoring-run"
        return rep
    rep = score(get_store(), QuestionRegistry())
    rep["source"] = "computed-live"
    return rep

@app.get("/v1/sessions/{session_id}")
def session(session_id: str):
    return get_store().session_messages(session_id)

@app.get("/v1/audit/{manifest_id}")
def audit(manifest_id: str):
    run = get_store().get_run(manifest_id)
    if not run:
        e = get_engines()
        return {"manifest_id": manifest_id, "kind": "forecast",
                "theta_hash": e.theta_hash, "seed": e.seed,
                "snapshot": e.situation["as_of"],
                "note": "cached-baseline artifact; reproduce via pipeline.py with this theta"}
    return run

# ---------------- UI ----------------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))

@app.get("/metrics")
def metrics():
    """Task 79: Prometheus exposition (RED + engine/NLU/entailment gauges)."""
    body, ctype = telemetry.render(uptime=time.time() - T0)
    return Response(content=body, media_type=ctype)

@app.get("/metrics.json")
def metrics_json():
    """Human/JSON metrics summary (back-compat with the pre-Prometheus /metrics)."""
    stats = get_store().answers_stats()
    stats["uptime_s"] = round(time.time() - T0, 1)
    stats["backend"] = get_settings().backend
    stats["nlu"] = nlu.get_metrics()        # Task 68: NLU layer counters
    stats["entailment"] = entail.get_metrics()   # Task 77: faithfulness-gate counters
    return JSONResponse(stats)

@app.get("/v1/nlu/health")
def nlu_health():
    """Task 68: NLU contamination report — grammar canary drift + injection-canary
    leakage + live counters. `contaminated` true means the parser regressed."""
    return JSONResponse(nlu.contamination_report())
