# Controls Matrix (human view)

Authoritative source: `controls.json`. Every row's evidence is a CI-run test.

| ID | Family | Control | Task | Evidence |
|----|--------|---------|------|----------|
| AC-1 | Access Control | OIDC/JWT auth + clearance claims | 74 | test_gateway.py |
| AC-2 | Access Control | Cell-level clearance redaction | 75 | test_redaction.py |
| AC-3 | Access Control | DLP egress export gate | 91 | test_dlp.py |
| AC-4 | Access Control | Dual-control θ promotion + audit chain | 89 | test_promotion.py |
| SI-1 | System Integrity | Prompt-injection defense + NLU hardening | 68 | test_injection.py, test_nlu_hardening.py |
| SI-2 | System Integrity | Faithfulness (entailment) gate | 77 | test_entailment.py |
| SI-3 | System Integrity | Source-family ablation (B8) | 67 | test_source_ablation.py |
| SI-4 | System Integrity | Parameter-attack robustness (θ-ball) | 65 | test_theta_ball.py |
| AU-1 | Audit & Accountability | Structured JSON logs + request-id | 80 | test_logging.py |
| AU-2 | Audit & Accountability | Prometheus RED + subsystem metrics | 79 | test_metrics.py |
| CP-1 | Contingency Planning | Graceful degradation | 70 | test_degradation.py |
| CP-2 | Contingency Planning | DR active-active (PG streaming) | 90 | test_dr.py |
| IR-1 | Incident Response | SLO-burn + security alerts | 81 | test_alerts.py |
| IR-2 | Incident Response | Operational runbook + drills | 72 | test_runbook.py |
| IR-3 | Incident Response | Quarterly red-team + postmortem | 88 | exercise1/test_exercise1.py |
| CM-1 | Configuration Management | No-regression ratchet gate | 94 | test_ratchet.py |
| CM-2 | Configuration Management | Versioned API contract + drift gate | 71 | test_openapi_export.py |
