# ARGUS Copilot — Pilot Onboarding Guide

Welcome. This pilot puts the ARGUS Strategic Intelligence Copilot in front of **20
analysts** for a structured evaluation. This guide gets you productive in ~15 minutes
and sets expectations about what to trust.

## What ARGUS is (and is not)

ARGUS is a **conversational copilot over a scored forecasting engine**. Every number it
shows — a probability, a band, a counterfactual delta — comes from the engine, not from a
language model. The optional LLM only parses your question into an intent; it never
produces a number.

It is **not** an oracle. It is a calibrated, auditable instrument for reasoning about
geopolitical and macro risk. Treat its outputs as **arguable evidence**, not verdicts.

## The five golden rules

1. **No naked numbers.** Every forecast ships with a band, evidence, a mechanism, a
   counterargument, and failure conditions. If you only read the headline number, you are
   misusing the tool.
2. **Abstention is a feature.** If ARGUS can't map your question to a scored forecast, it
   abstains rather than guessing. An abstention is information.
3. **Calibration is legible.** Each forecast carries a track-record badge ("forecasts near
   70% verified 68% of the time, n=…"). Weight the number by its track record.
4. **Clearance-aware.** You see only what your clearance permits; redacted items are marked.
   Do not attempt to infer withheld content.
5. **Degraded ≠ wrong.** If the live engine is down, ARGUS serves the last validated
   snapshot with a staleness banner. Note the "as of" date before acting.

## Getting started

- **Ask a question:** `POST /v1/ask {"text": "...", "persona": "analyst"}`. Intents:
  forecast, why/cause, what-if, policy, early-warning, vulnerability, analogs, scenarios,
  status. Example: *"What's the probability of a second Hormuz closure by 2027?"*
- **Personas:** `principal` (headline + counter-case), `analyst` (full detail), `planner`
  (policy focus), `watch` (early-warning focus).
- **What-if:** *"What if we deploy a Gulf maritime verification coalition?"* returns a
  paired counterfactual with assumptions.
- **Audit anything:** every answer carries a `manifest_id`; `GET /v1/audit/{id}` reproduces it.

## What to trust, and how to challenge it

- Trust the **band** more than the point estimate; trust forecasts with **n ≥ 10** track
  record more than model-only ones.
- Read the **counterargument** and **failure conditions** every time.
- **Disagree?** File a dissent (see right-of-reply): it is signed by you and travels with the
  forecast for every future reader. Your dissent is part of the record.

## Pilot scope & support

- **Cohort:** 20 analysts, 6-week pilot. **Channel:** #argus-pilot. **On-call:** see
  `docs/RUNBOOK.md`.
- **Feedback is mandatory weekly** (see `FEEDBACK.md`) and **consent is required before
  access** (see `CONSENT.md`).
- **Do not** paste classified material above the system's accreditation level into queries.
