# ARGUS — Accreditation Evidence Pack

**System:** ARGUS Strategic Intelligence Copilot · **Version:** 3.0.0 · **Status:** submitted

This pack maps the system's security/assurance controls (build-plan tasks 74–91, plus the
supporting integrity/availability controls) to their implementation and to **machine-checkable
evidence** — every control cites code and a test that runs in CI. The authoritative,
machine-readable matrix is `controls.json` (guarded by `tests/test_accreditation.py`, which
fails if any cited artifact is missing).

## Contents
- `controls.json` — control → implementation → evidence (source of truth).
- `controls_matrix.md` — human-readable matrix.
- Evidence runs in CI (`.github/workflows/ci.yml`): unit/integration suite, red-team gates,
  contamination gate, ratchet gate, OpenAPI drift, promtool alert tests, helm lint/template.

## Submission checklist
- [x] Access control: authN/Z, clearance, redaction, DLP, dual-control (AC-1..4)
- [x] System integrity: injection defense, faithfulness gate, source-ablation, robustness (SI-1..4)
- [x] Audit & accountability: structured logs + request-id, metrics (AU-1..2)
- [x] Contingency planning: graceful degradation, DR active-active (CP-1..2)
- [x] Incident response: alerts, runbook, quarterly red-team + postmortem (IR-1..3)
- [x] Configuration management: no-regression ratchet, versioned API contract (CM-1..2)
- [x] Every control's evidence artifact exists and its test passes in CI

## How to verify
```bash
python -m pytest tests/test_accreditation.py -q      # evidence artifacts present
scripts/cut_release.sh --check                        # all control gates green
```
