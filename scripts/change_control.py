"""Task 99 — change-control freeze gate (CI-enforced).

Blocks production releases during a declared freeze window unless the change is an
emergency or has CAB (Change Advisory Board) approval. Wired into the release-gated CI
job; run locally with --date to test a window.

    python scripts/change_control.py                     # gate on today's date
    python scripts/change_control.py --date 2026-12-20   # simulate a freeze day
    CAB_APPROVED=1 python scripts/change_control.py       # CAB override
"""
from __future__ import annotations
import argparse, json, os
from datetime import date

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FREEZE_FILE = os.path.join(_ROOT, "deploy", "change-control", "freeze-windows.json")


def load_windows(path: str = FREEZE_FILE) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("windows", [])


def in_freeze(d: date, windows: list[dict] | None = None) -> dict | None:
    for w in (windows if windows is not None else load_windows()):
        if date.fromisoformat(w["start"]) <= d <= date.fromisoformat(w["end"]):
            return w
    return None


def check(on: str | None = None, emergency: bool = False, cab_approved: bool = False,
          windows: list[dict] | None = None) -> dict:
    d = date.fromisoformat(on) if on else date.today()
    w = in_freeze(d, windows)
    if w is None:
        return {"date": d.isoformat(), "in_freeze": False, "allowed": True,
                "reason": "outside freeze window"}
    allowed = emergency or cab_approved
    return {"date": d.isoformat(), "in_freeze": True, "window": w["name"],
            "allowed": allowed,
            "reason": ("emergency override" if emergency else
                       "CAB approved" if cab_approved else
                       f"BLOCKED by freeze '{w['name']}' — CAB approval required")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--emergency", action="store_true")
    ap.add_argument("--cab-approved", action="store_true")
    a = ap.parse_args()
    emergency = a.emergency or os.environ.get("CHANGE_EMERGENCY") == "1"
    cab = a.cab_approved or os.environ.get("CAB_APPROVED") == "1"
    r = check(a.date, emergency, cab)
    print(json.dumps(r))
    if not r["allowed"]:
        print("CHANGE-CONTROL: BLOCKED —", r["reason"])
        return 1
    print("CHANGE-CONTROL: OK —", r["reason"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
