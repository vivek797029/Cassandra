"""Task 78 — offline Helm chart validator.

A stand-in for `helm lint`/`helm template` when the helm binary isn't available
(restricted network). It (1) YAML-parses Chart.yaml and every values file, (2)
renders each template structurally — dropping control-only template lines and
substituting value expressions with a placeholder — then YAML-parses the result,
catching indentation/nesting errors. Authoritative `helm lint`/`helm template`
still run in CI (see .github/workflows/ci.yml `helm` job).

    python deploy/helm/validate_chart.py
"""
from __future__ import annotations
import os, re, sys, yaml

CHART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "argus")
_TPL = re.compile(r"{{.*?}}")


def _render(text: str) -> str:
    out = []
    for line in text.splitlines():
        if not line.strip():
            out.append(line)
            continue
        stripped = _TPL.sub("", line)
        if stripped.strip() == "":          # control-only line ({{ if }}, toYaml, include…)
            continue
        out.append(_TPL.sub("x", line))     # substitute value expressions
    return "\n".join(out)


def main() -> int:
    errs: list[str] = []

    chart = yaml.safe_load(open(os.path.join(CHART, "Chart.yaml")))
    for req in ("apiVersion", "name", "version", "appVersion"):
        if req not in chart:
            errs.append(f"Chart.yaml missing {req}")

    base = yaml.safe_load(open(os.path.join(CHART, "values.yaml"))) or {}
    for vf in ("values.yaml", "values-dev.yaml", "values-prod.yaml"):
        p = os.path.join(CHART, vf)
        if not os.path.exists(p):
            errs.append(f"missing {vf}"); continue
        try:
            ov = yaml.safe_load(open(p)) or {}
        except yaml.YAMLError as e:
            errs.append(f"{vf}: YAML error {e}"); continue
        for k in ov:                        # overrides should target known keys
            if vf != "values.yaml" and k not in base:
                errs.append(f"{vf}: unknown top-level key '{k}'")

    tdir = os.path.join(CHART, "templates")
    rendered = 0
    for fn in sorted(os.listdir(tdir)):
        if fn in ("_helpers.tpl", "NOTES.txt"):
            continue
        text = open(os.path.join(tdir, fn)).read()
        try:
            docs = list(yaml.safe_load_all(_render(text)))
            rendered += 1
            for d in docs:
                if d and "kind" not in d:
                    errs.append(f"{fn}: a document has no 'kind'")
        except yaml.YAMLError as e:
            errs.append(f"{fn}: structural YAML error {e}")

    if errs:
        print("CHART VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
        return 1
    print(f"chart OK — Chart.yaml + 3 values files parsed; {rendered} templates render to valid YAML")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
