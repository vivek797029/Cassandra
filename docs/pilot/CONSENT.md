# ARGUS Pilot — Informed Consent

Please read and sign before being granted pilot access.

## Purpose
You are invited to evaluate the ARGUS Strategic Intelligence Copilot during a 6-week
pilot. The goal is to assess usefulness, calibration trust, and faithfulness in real
analytic workflows.

## What is collected
- **Your queries** and the copilot's responses (with `manifest_id` for reproducibility).
- **Your feedback** (weekly forms, per-answer ratings) and any **dissents** you file
  (these are signed with your identity and retained with the forecast).
- **Telemetry**: request id, latency, intent, and clearance level (no free-text beyond your
  queries). Logs are JSON with a request id for tracing.

## How it is handled
- Data stays within the system's accreditation boundary; clearance-based redaction applies.
- Your queries are **not** used to make automated decisions about you.
- Aggregated, de-identified findings may inform the post-pilot report.

## Your rights
- Participation is **voluntary**; you may **withdraw at any time** with no penalty, and
  request deletion of your feedback (dissents attached to shipped forecasts are retained as
  part of the analytic record, but may be de-identified on request).
- You can review what is stored about your session via `GET /v1/sessions/{id}`.

## Acknowledgement
By signing you confirm you understand the above, will not input material above the system's
accreditation level, and consent to the data handling described.

```
Name: ______________________   Clearance: __________   Date: __________

Signature: __________________   Pilot ID: __________
```
