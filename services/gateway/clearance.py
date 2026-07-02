"""Task 74 — clearance model.

A total order over classification levels and the verified `Principal` derived from
a token's claims. Unknown / missing clearance fails CLOSED to OPEN (least privilege)
so a malformed claim can never widen access. Task 75 uses `Principal.can_access`
for cell-level redaction.
"""
from __future__ import annotations
from dataclasses import dataclass, field

# Total order, low → high. Aliases map common spellings onto canonical names.
CLEARANCE_ORDER = {"OPEN": 0, "CONFIDENTIAL": 1, "SECRET": 2, "TOPSECRET": 3}
_ALIASES = {"PUBLIC": "OPEN", "UNCLASSIFIED": "OPEN", "U": "OPEN",
            "CONF": "CONFIDENTIAL", "C": "CONFIDENTIAL",
            "S": "SECRET", "TS": "TOPSECRET", "TOP_SECRET": "TOPSECRET",
            "TOP-SECRET": "TOPSECRET"}
DEFAULT_CLEARANCE = "OPEN"


def normalize_clearance(value: str | None) -> str:
    """Canonical clearance name; anything unrecognized → OPEN (fail closed)."""
    if not value:
        return DEFAULT_CLEARANCE
    v = str(value).strip().upper().replace(" ", "_")
    v = _ALIASES.get(v, v)
    return v if v in CLEARANCE_ORDER else DEFAULT_CLEARANCE


def level_of(clearance: str | None) -> int:
    return CLEARANCE_ORDER[normalize_clearance(clearance)]


@dataclass
class Principal:
    sub: str
    clearance: str = DEFAULT_CLEARANCE
    scopes: list[str] = field(default_factory=list)
    persona: str = "analyst"
    compartments: list[str] = field(default_factory=list)
    claims: dict = field(default_factory=dict)

    def __post_init__(self):
        self.clearance = normalize_clearance(self.clearance)

    @property
    def level(self) -> int:
        return CLEARANCE_ORDER[self.clearance]

    def can_access(self, required: str) -> bool:
        """True iff this principal's clearance is at least `required`."""
        return self.level >= level_of(required)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def to_dict(self) -> dict:
        return {"sub": self.sub, "clearance": self.clearance, "level": self.level,
                "scopes": self.scopes, "persona": self.persona,
                "compartments": self.compartments}


def principal_from_claims(claims: dict, clearance_claim: str = "clearance") -> Principal:
    """Map verified JWT claims onto a Principal. `scope` (OAuth space-delimited) and
    `scopes` (list) are both accepted; persona defaults to analyst."""
    scope_raw = claims.get("scope") or claims.get("scopes") or []
    scopes = scope_raw.split() if isinstance(scope_raw, str) else list(scope_raw)
    comp = claims.get("compartments") or claims.get("compartment") or []
    if isinstance(comp, str):
        comp = [c for c in comp.replace(",", " ").split() if c]
    return Principal(
        sub=str(claims.get("sub", "unknown")),
        clearance=normalize_clearance(claims.get(clearance_claim)),
        scopes=scopes,
        persona=str(claims.get("persona", "analyst")),
        compartments=list(comp),
        claims=claims,
    )
