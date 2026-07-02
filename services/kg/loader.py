"""Task 55 — TCKG loader: situation.json + mechanisms -> Neo4j (MERGE-idempotent).

Generates a deterministic, idempotent Cypher batch from the evidence layer:
  facts    -> (:Claim {id}) + (:Source {id}) + FROM_SOURCE
  signals  -> (:Claim {id, kind:'signal'}) + EVIDENCED_BY links to fact claims
  analogs  -> (:Case {id}) with lesson/outcome props
  variables/mechanisms -> the db/neo4j/schema.cypher seed set, with mechanism
              params refreshed from the DEPLOYED theta when available

Execution: if NEO4J_URI is configured and the `neo4j` driver is importable,
statements run against the live graph; otherwise they are written to
output/kg_load.cypher for `cypher-shell -f` (same statements either way).
MERGE-only (plus SET) => running twice is a no-op by construction.

CLI:  python -m services.kg.loader [--out PATH]
"""
from __future__ import annotations
import argparse, json, os, re, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.copilot.config import get_settings
from core.phases import load_situation

OUT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                           "output", "kg_load.cypher")

def esc(s) -> str:
    return str(s).replace("\\", "\\\\").replace("'", "\\'")

def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")[:60]

VARIABLES = [("me_regime", "Middle East conflict regime", "security", None),
             ("brent_usd", "Brent crude", "economic", "USD/bbl"),
             ("infl_global", "Global headline inflation", "economic", "%"),
             ("growth_global", "Global GDP growth", "economic", "%"),
             ("food_idx", "Food price index", "environmental", None),
             ("em_defaults", "EM default events", "economic", None)]

from services.kg.mechanisms import MECHANISM_CARDS
# graph cards limited to cross-variable mechanisms (self-loop hazards stay sim-side)
MECHS = [(c["id"], c["from"], c["to"], c["form"], c["id_status"], c["sign"],
          c["lag_q"], c["params"]) for c in MECHANISM_CARDS if c["from"] != c["to"]]

def _deployed_theta() -> dict:
    try:
        with open(get_settings().theta_cache) as f:
            d = json.load(f)
        return dict(zip(d["names"], d["theta"]))
    except Exception:
        return {}

def generate_statements(situation: dict | None = None) -> list[str]:
    sit = situation or load_situation()
    th = _deployed_theta()
    stmts: list[str] = []
    for key, name, domain, unit in VARIABLES:
        s = (f"MERGE (v:Variable {{key:'{key}'}}) SET v.name='{esc(name)}', "
             f"v.domain='{domain}'" + (f", v.unit='{esc(unit)}'" if unit else ""))
        stmts.append(s + ";")
    for mid, vfrom, vto, form, status, sign, lag, pkeys in MECHS:
        params = {k: round(th[k], 5) for k in pkeys if k in th}
        stmts.append(
            f"MERGE (m:Mechanism {{id:'{mid}'}}) SET m.form='{form}', "
            f"m.id_status='{status}', m.sign={sign}, m.lag_q={lag}, "
            f"m.params_json='{esc(json.dumps(params))}';")
        stmts.append(f"MATCH (m:Mechanism {{id:'{mid}'}}), (a:Variable {{key:'{vfrom}'}}), "
                     f"(b:Variable {{key:'{vto}'}}) MERGE (m)-[:FROM_VAR]->(a) "
                     f"MERGE (m)-[:TO_VAR]->(b);")
    for f in sit["facts"]:
        src = slug(f["source"])
        stmts.append(f"MERGE (c:Claim {{id:'{f['id']}'}}) SET c.kind='fact', "
                     f"c.text='{esc(f['text'])}', c.domain='{f['domain']}';")
        stmts.append(f"MERGE (s:Source {{id:'{src}'}}) SET s.name='{esc(f['source'])}';")
        stmts.append(f"MATCH (c:Claim {{id:'{f['id']}'}}), (s:Source {{id:'{src}'}}) "
                     f"MERGE (c)-[:FROM_SOURCE]->(s);")
    for sig in sit["signals"]:
        sid = "sig_" + slug(sig["name"])
        stmts.append(f"MERGE (c:Claim {{id:'{sid}'}}) SET c.kind='signal', "
                     f"c.text='{esc(sig['name'])}', c.strength={sig['strength']}, "
                     f"c.reliability={sig['reliability']};")
        for fid in sig.get("fact_ids", []):
            stmts.append(f"MATCH (a:Claim {{id:'{sid}'}}), (b:Claim {{id:'{fid}'}}) "
                         f"MERGE (a)-[:SUPPORTS]->(b);")
    for a in sit["analogs"]:
        aid = "case_" + slug(a["name"])
        stmts.append(f"MERGE (k:Case {{id:'{aid}'}}) SET k.name='{esc(a['name'])}', "
                     f"k.similarity={a['similarity']}, k.lesson='{esc(a['lesson'])}', "
                     f"k.outcome='{esc(a['outcome'])}';")
    return stmts

def load(out_path: str | None = None) -> dict:
    stmts = generate_statements()
    s = get_settings()
    if s.neo4j_uri and s.neo4j_password:
        try:
            from neo4j import GraphDatabase
            drv = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
            with drv.session() as ses:
                for st in stmts:
                    ses.run(st.rstrip(";"))
            drv.close()
            return {"mode": "neo4j", "statements": len(stmts), "uri": s.neo4j_uri}
        except Exception as ex:                      # fall through to file
            err = str(ex)[:120]
    out = out_path or OUT_DEFAULT
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        f.write("// generated by services/kg/loader.py — MERGE-idempotent\n")
        f.write("\n".join(stmts) + "\n")
    res = {"mode": "cypher-file", "statements": len(stmts), "path": out}
    if s.neo4j_uri:
        res["neo4j_error"] = err            # configured but unreachable
    return res

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    print(json.dumps(load(ap.parse_args().out), indent=1))

if __name__ == "__main__":
    main()
