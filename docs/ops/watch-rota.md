# ARGUS Watch Rota — 24/7 Coverage

Follow-the-sun coverage with a primary and a secondary on-call at all times.

## Shifts (follow-the-sun)
| Shift | Hours (UTC) | Region | Primary | Secondary |
|-------|-------------|--------|---------|-----------|
| A | 00:00–08:00 | APAC | rotates weekly | next-in-rota |
| B | 08:00–16:00 | EMEA | rotates weekly | next-in-rota |
| C | 16:00–24:00 | AMER | rotates weekly | next-in-rota |

- **Primary** owns acknowledgement + first response within the severity SLA
  (`docs/ops/escalation-policy.md`).
- **Secondary** is the escalation target and covers if primary doesn't ack in time.
- **Handoff** at each shift boundary: 10-minute sync, open-incident review, and a note in
  #argus-oncall (active alerts, degraded state, in-flight changes).
- **Rotation** is weekly; a published calendar names primary/secondary per shift 4 weeks out.

## Responsibilities
- Watch the Grafana board (`deploy/observability/grafana-argus.json`) and PagerDuty/Alertmanager.
- Follow `docs/RUNBOOK.md` for triage; page per `escalation-policy.md`.
- File a short shift report; escalate Sev-1 to the incident commander immediately.
