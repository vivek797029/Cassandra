"""Task 71 — OpenAPI reference export.

Dumps the live FastAPI schema to a deterministic, versioned JSON artifact so the
API contract is reviewable in diffs and publishable in CI.

  python scripts/export_openapi.py            # write docs/openapi/openapi.json (+ pinned)
  python scripts/export_openapi.py --check    # CI drift gate: fail if committed != live
  python scripts/export_openapi.py --out DIR  # custom output directory

The schema is serialized with sort_keys=True + indent=2 so the committed file is
stable across runs and machines; `--check` regenerates in memory and compares,
failing (exit 1) when someone changed a route without re-exporting.
"""
from __future__ import annotations
import os, sys, json, argparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
# Keep the import light & side-effect-free: app.openapi() introspects routes only
# (no startup warm / engine training needed).
os.environ.setdefault("ARGUS_FAST", "1")

DEFAULT_OUT = os.path.join(ROOT, "docs", "openapi")


def build_spec() -> dict:
    from services.copilot.main import app
    return app.openapi()


def canonical(spec: dict) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _paths(out_dir: str, version: str) -> tuple[str, str]:
    return (os.path.join(out_dir, "openapi.json"),
            os.path.join(out_dir, f"openapi-{version}.json"))


def write(out_dir: str = DEFAULT_OUT) -> list[str]:
    spec = build_spec()
    version = spec.get("info", {}).get("version", "0.0.0")
    text = canonical(spec)
    os.makedirs(out_dir, exist_ok=True)
    latest, pinned = _paths(out_dir, version)
    for p in (latest, pinned):
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    return [latest, pinned]


def check(out_dir: str = DEFAULT_OUT) -> tuple[bool, str]:
    spec = build_spec()
    version = spec.get("info", {}).get("version", "0.0.0")
    want = canonical(spec)
    latest, pinned = _paths(out_dir, version)
    for p in (latest, pinned):
        if not os.path.exists(p):
            return False, f"missing {os.path.relpath(p, ROOT)} — run: python scripts/export_openapi.py"
        with open(p, encoding="utf-8") as f:
            if f.read() != want:
                return False, (f"{os.path.relpath(p, ROOT)} is stale — the live API schema "
                               "changed. Re-run: python scripts/export_openapi.py")
    return True, f"OpenAPI v{version} in sync ({len(spec.get('paths', {}))} paths)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export/verify the OpenAPI artifact")
    ap.add_argument("--check", action="store_true", help="drift gate: committed vs live (no write)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    args = ap.parse_args()
    if args.check:
        ok, msg = check(args.out)
        print(("OK: " if ok else "DRIFT: ") + msg)
        return 0 if ok else 1
    paths = write(args.out)
    spec = build_spec()
    print(f"wrote OpenAPI v{spec['info']['version']} "
          f"({len(spec.get('paths', {}))} paths):")
    for p in paths:
        print(f"  {os.path.relpath(p, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
