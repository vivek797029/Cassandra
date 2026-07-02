"""Task 74 — FastAPI auth dependencies.

`require_principal` resolves the caller. When auth is disabled (dev / back-compat)
it returns a trusted local principal so existing endpoints keep working without a
token; when enabled it requires a valid bearer JWT (401 otherwise).
`require_clearance(level)` is the 403 gate Task 75 builds redaction on.
"""
from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from services.copilot.config import get_settings
from services.gateway import auth
from services.gateway.clearance import Principal, principal_from_claims

_bearer = HTTPBearer(auto_error=False, description="OIDC/JWT bearer token")


def get_principal(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    s = get_settings()
    if not s.auth_enabled:
        # Trusted local caller. Clearance from ARGUS_AUTH_DEV_CLEARANCE (default SECRET).
        return Principal(sub="dev-local", clearance=s.auth_dev_clearance,
                         scopes=["*"], persona="analyst")
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = auth.verify_token(creds.credentials, s)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e.reason}",
                            headers={"WWW-Authenticate": "Bearer"})
    return principal_from_claims(claims, s.clearance_claim)


# alias used at call sites
require_principal = get_principal


def require_clearance(level: str):
    """Dependency factory: 403 unless the principal is cleared to `level` or higher."""
    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can_access(level):
            raise HTTPException(
                status_code=403,
                detail=f"insufficient clearance: {principal.clearance} < required {level}")
        return principal
    return _dep


def require_scope(scope: str):
    """Dependency factory: 403 unless the principal holds `scope` (or wildcard)."""
    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if "*" not in principal.scopes and not principal.has_scope(scope):
            raise HTTPException(status_code=403, detail=f"missing scope: {scope}")
        return principal
    return _dep
