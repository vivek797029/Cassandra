# Change Control (Task 99)

Production changes follow a Change Advisory Board (CAB) process with declared freeze
windows, **enforced in CI** by `scripts/change_control.py` (freeze list:
`deploy/change-control/freeze-windows.json`).

## Release calendar
- **Standard releases:** weekly, Tuesdays, outside freeze windows; must pass the full
  release gate (`scripts/cut_release.sh --check`) and the ratchet regression gate (Task 94).
- **Freeze windows:** go-live hypercare (2026-07-01 → 07-15) and year-end
  (2026-12-18 → 2027-01-02). No non-emergency production change during a freeze.

## CAB
- **Membership:** eng lead, SRE on-call lead, security, product owner.
- **Normal change:** PR + green CI + CAB sign-off (recorded) → release.
- **Emergency change:** on-call may proceed with post-hoc CAB review within 24h; set
  `CHANGE_EMERGENCY=1` for the CI gate and file the record.
- **Freeze exception:** requires explicit CAB approval (`CAB_APPROVED=1`) with justification.

## CI enforcement
The release-gated `docker` job runs `python scripts/change_control.py`. During a freeze the
job **fails** (exit 1) unless `CHANGE_EMERGENCY=1` or `CAB_APPROVED=1` is set, so a release
cannot ship mid-freeze without a recorded override.

## Records
Every override (emergency / CAB) is logged with date, author, justification, and linked to
the release tag and the θ-promotion audit chain (Task 89) where relevant.
