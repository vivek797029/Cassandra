# ARGUS Escalation Policy

Alerts are defined in `deploy/observability/alerts.yaml` (Task 81) and routed by
`services/ops/escalation.py`. Severity → action, tier, and SLA:

| Severity | Action | Tier | Ack SLA | Escalate after | Escalate to |
|----------|--------|------|---------|----------------|-------------|
| `page` | Page | primary-oncall | 15 min | 15 min | secondary-oncall |
| `warning` | Notify (channel) | oncall-channel | 60 min | 120 min | team-lead |
| `ticket` | File ticket | backlog | 1 day | — | — |

## Ladder
1. **Alert fires** → Alertmanager routes by `severity` label.
2. **Primary** acks within the SLA and starts triage (`docs/RUNBOOK.md`).
3. **No ack in SLA** → auto-escalate to **secondary-oncall**.
4. **Sev-1** (data fabrication / faithfulness break, θ leak, coordinated poisoning) →
   page primary **and** the **incident commander**; freeze θ promotions; preserve manifests.
5. **Comms:** status updates in #argus-incident every 30 min until resolved; blameless
   postmortem within 48h.

## Alert → severity (current)
- **page:** ArgusHighErrorRate, ArgusErrorBudgetFastBurn, ArgusHighLatencyP99,
  ArgusEngineDown, ArgusDegraded, ArgusTargetMissing
- **warning:** ArgusPromptInjectionSpike
- **ticket:** ArgusEntailmentViolations
