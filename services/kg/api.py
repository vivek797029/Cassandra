"""Task 56 — evidence API: /v1/evidence/{key} chains (graph-backed with local mirror).

Returns the full evidence chain behind a forecast key: fact claims with
sources, the causal mechanism, the historical analog, the counterargument,
and the id-status note. Provider selection:
  * Neo4jProvider when NEO4J_URI configured (queries Claim/Source/Mechanism)
  * LocalProvider otherwise — reads the same content from data/situation.json
    (which is exactly what the loader MERGEs into the graph, so both providers
    return identical chains by construction).
"""
from __future__ import annotations
import os, sys

from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.copilot.config import get_settings
from core.phases import load_situation

router = APIRouter(prefix="/v1/evidence", tags=["knowledge-graph"])


class LocalProvider:
    mode = "local-mirror"

    def __init__(self):
        self.sit = load_situation()
        self.facts = {f["id"]: f for f in self.sit["facts"]}

    def keys(self) -> list[str]:
        return sorted(self.sit["explanations"].keys())

    def chain(self, key: str) -> dict | None:
        exp = self.sit["explanations"].get(key)
        if not exp:
            return None
        return {
            "key": key,
            "facts": [self.facts[i] for i in exp.get("evidence", []) if i in self.facts],
            "mechanism": exp.get("mechanism", ""),
            "historical_analog": exp.get("analog", ""),
            "counterargument": exp.get("counter", ""),
            "failure_conditions": exp.get("failure", []),
            "confidence": exp.get("confidence", "low"),
            "provider": self.mode,
        }


class Neo4jProvider(LocalProvider):
    """Graph-backed chains; falls back to the local mirror per-query on error."""
    mode = "neo4j"

    def __init__(self, uri: str, user: str, password: str):
        super().__init__()
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def chain(self, key: str) -> dict | None:
        base = super().chain(key)
        if base is None:
            return None
        try:
            with self.driver.session() as ses:
                ids = [f["id"] for f in base["facts"]]
                rows = ses.run(
                    "MATCH (c:Claim)-[:FROM_SOURCE]->(s:Source) WHERE c.id IN $ids "
                    "RETURN c.id AS id, c.text AS text, c.domain AS domain, "
                    "s.name AS source", ids=ids).data()
            if rows:
                base["facts"] = rows
                base["provider"] = self.mode
        except Exception:
            base["provider"] = "local-mirror (neo4j unreachable)"
        return base


_PROVIDER = None

def get_provider():
    global _PROVIDER
    if _PROVIDER is None:
        s = get_settings()
        if s.neo4j_uri and s.neo4j_password:
            try:
                _PROVIDER = Neo4jProvider(s.neo4j_uri, s.neo4j_user, s.neo4j_password)
            except Exception:
                _PROVIDER = LocalProvider()
        else:
            _PROVIDER = LocalProvider()
    return _PROVIDER

def reset_provider():
    global _PROVIDER
    _PROVIDER = None


@router.get("")
def list_keys():
    p = get_provider()
    return {"keys": p.keys(), "provider": p.mode}

@router.get("/{key}")
def evidence(key: str):
    chain = get_provider().chain(key)
    if chain is None:
        raise HTTPException(404, f"no evidence chain for '{key}'")
    return chain
