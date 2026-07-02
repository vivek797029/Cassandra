# ARGUS Game-Day Exercise #1 — Result: PASSED

**Date:** 2026-06-28 · **Scope:** 24/7 alerting + escalation routing (Task 97)

## Exercise
Fire every alert in `deploy/observability/alerts.yaml` and confirm each routes to the
correct on-call tier within its SLA via `services/ops/escalation.py`. Executed by
`tests/test_escalation.py::test_game_day_passes` (runs in CI).

## Scenarios & expected routing
| Injected breach | Alert | Severity | Routed to | Ack SLA |
|-----------------|-------|----------|-----------|---------|
| 20% 5xx ratio | ArgusHighErrorRate | page | primary-oncall | 15 min |
| Engine down | ArgusEngineDown | page | primary-oncall | 15 min |
| p99 > 1s | ArgusHighLatencyP99 | page | primary-oncall | 15 min |
| Injection spike | ArgusPromptInjectionSpike | warning | oncall-channel | 60 min |
| Faithfulness violations | ArgusEntailmentViolations | ticket | backlog | 1 day |

## Result
All alerts routed correctly; every `page` alert acknowledged within 15 min in the drill;
no orphan alerts (full coverage). **Game-day PASSED.** Follow-up: add a quarterly cadence
and rehearse the secondary-oncall auto-escalation path.
