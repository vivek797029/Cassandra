"""ARGUS — question registry API router (Task 47). Mounted into the copilot app."""
from __future__ import annotations
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.question_registry.registry import QuestionRegistry, seed_from_engines

router = APIRouter(prefix="/v1/questions", tags=["question-registry"])

_REG: QuestionRegistry | None = None

def get_registry() -> QuestionRegistry:
    global _REG
    if _REG is None:
        _REG = QuestionRegistry()
        seed_from_engines(_REG)
    return _REG

def reset_registry():
    global _REG
    _REG = None


class QuestionCreate(BaseModel):
    key: str
    text: str
    domain: str = "political"
    horizon: Optional[str] = None
    resolution_rule: dict = {"type": "manual"}

class ResolveBody(BaseModel):
    outcome: int                      # 0 | 1


def _out(q: dict) -> dict:
    q = dict(q)
    if isinstance(q.get("resolution_rule"), str):
        try:
            q["resolution_rule"] = json.loads(q["resolution_rule"])
        except (TypeError, json.JSONDecodeError):
            pass
    return q


@router.get("")
def list_questions(resolved: Optional[bool] = None, domain: Optional[str] = None):
    return [_out(q) for q in get_registry().list(resolved=resolved, domain=domain)]

@router.get("/{key}")
def get_question(key: str):
    q = get_registry().get(key)
    if not q:
        raise HTTPException(404, f"unknown question '{key}'")
    return _out(q)

@router.post("", status_code=201)
def create_question(body: QuestionCreate):
    try:
        get_registry().create(body.key, body.text, body.domain, body.horizon,
                              body.resolution_rule, if_exists="error")
    except KeyError as ex:
        raise HTTPException(409, str(ex))
    return _out(get_registry().get(body.key))

@router.post("/{key}/resolve")
def resolve_question(key: str, body: ResolveBody):
    if body.outcome not in (0, 1):
        raise HTTPException(422, "outcome must be 0 or 1")
    try:
        return _out(get_registry().resolve(key, body.outcome))
    except KeyError:
        raise HTTPException(404, f"unknown question '{key}'")

@router.post("/resolver/run")
def run_resolver():
    """Task 48: auto-resolve pending questions against observed data."""
    from services.question_registry.resolver import resolve_pending
    rep = resolve_pending(get_registry())
    rep.pop("details", None) if len(rep.get("details", [])) > 50 else None
    return rep
