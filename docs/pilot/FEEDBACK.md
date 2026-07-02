# ARGUS Pilot — Feedback Form

Two channels: a quick **per-answer** rating and a **weekly** survey. Submit weekly to
#argus-pilot or via the form endpoint.

## Per-answer (attach the `manifest_id`)
For any answer worth flagging:

- `manifest_id`: __________
- **Useful?** (1–5): ___
- **Did you trust the number given its calibration badge?** (yes / partly / no): ___
- **Faithful?** Did every sentence map to evidence/objects? (yes / no — quote the issue): ___
- **Missing evidence or mechanism?** (free text): ___
- **Did you file a dissent?** (yes / no). If yes, dissent id: ___

## Weekly survey
1. How many ARGUS queries did you run this week, and for what tasks?
2. Where did ARGUS **change or sharpen** a judgment you would otherwise have made?
3. Where did it **mislead or frustrate** you? (calibration, latency, abstention, redaction)
4. Did you hit **degraded mode** or any error? (describe; include request id if known)
5. Calibration trust this week (1–5): ___  Faithfulness trust (1–5): ___
6. One thing to fix before a wider rollout: ___

## Incident reporting
If you suspect an **ungrounded number**, a **prompt-injection** that affected output, or a
**clearance leak**, report immediately to #argus-pilot with the `manifest_id` and a
screenshot. These are tracked as Sev-2+ per `docs/RUNBOOK.md`.
