"""Task 89 — theta promotion workflow with dual-control sign-off + audit chain.

theta is the national vulnerability map; promoting a new champion is a privileged,
two-person action (separation of duties). A promotion requires a request plus TWO
DISTINCT approvers who are NOT the requester; only then is the underlying
`store.theta_promote` (Task 53) allowed to run. Every step is appended to a
hash-linked, tamper-evident audit chain (and mirrored to the store audit log).
An unsigned / under-approved promotion is rejected.
"""
from __future__ import annotations
import hashlib, time

from services.copilot.store import get_store


class PromotionError(Exception):
    pass


class ThetaPromotionWorkflow:
    MIN_APPROVALS = 2

    def __init__(self, store=None):
        self.store = store or get_store()
        self._pending: dict[str, dict] = {}     # theta_hash -> {requester, approvers:set, reason}
        self.chain: list[dict] = []             # hash-linked audit chain

    # -- audit chain ----------------------------------------------------------
    def _append(self, actor: str, action: str, detail: str) -> None:
        prev = self.chain[-1]["hash"] if self.chain else "genesis"
        ts = time.time()
        h = hashlib.sha256(f"{prev}|{actor}|{action}|{detail}|{ts}".encode()).hexdigest()[:16]
        self.chain.append({"actor": actor, "action": action, "detail": detail,
                           "ts": ts, "prev": prev, "hash": h})
        try:
            self.store.audit(actor, action, detail)     # durable mirror
        except Exception:
            pass

    def verify_chain(self) -> bool:
        prev = "genesis"
        for e in self.chain:
            h = hashlib.sha256(f"{prev}|{e['actor']}|{e['action']}|{e['detail']}|{e['ts']}"
                               .encode()).hexdigest()[:16]
            if h != e["hash"] or e["prev"] != prev:
                return False
            prev = e["hash"]
        return True

    # -- workflow -------------------------------------------------------------
    def request(self, theta_hash: str, requester: str, reason: str = "") -> dict:
        self._pending[theta_hash] = {"requester": requester, "approvers": set(), "reason": reason}
        self._append(requester, "theta.promotion.request", f"{theta_hash}: {reason}")
        return self.status(theta_hash)

    def approve(self, theta_hash: str, approver: str) -> dict:
        p = self._pending.get(theta_hash)
        if p is None:
            raise PromotionError("no open promotion request for this theta")
        if approver == p["requester"]:
            raise PromotionError("requester cannot self-approve (dual control)")
        p["approvers"].add(approver)
        self._append(approver, "theta.promotion.approve", theta_hash)
        return self.status(theta_hash)

    def status(self, theta_hash: str) -> dict:
        p = self._pending.get(theta_hash)
        n = len(p["approvers"]) if p else 0
        return {"theta_hash": theta_hash, "approvals": n, "required": self.MIN_APPROVALS,
                "approvers": sorted(p["approvers"]) if p else [],
                "ready": n >= self.MIN_APPROVALS}

    def promote(self, theta_hash: str) -> dict:
        st = self.status(theta_hash)
        if not st["ready"]:
            self._append("system", "theta.promotion.reject",
                         f"{theta_hash}: insufficient sign-off ({st['approvals']}/{self.MIN_APPROVALS})")
            raise PromotionError(
                f"unsigned theta rejected: {st['approvals']}/{self.MIN_APPROVALS} approvals")
        self.store.theta_promote(theta_hash)            # Task 53 promotion, now gated
        self._append("system", "theta.promotion.promote", theta_hash)
        self._pending.pop(theta_hash, None)
        return {**self.status(theta_hash), "promoted": True}


_WORKFLOW: ThetaPromotionWorkflow | None = None


def get_promotion_workflow() -> ThetaPromotionWorkflow:
    global _WORKFLOW
    if _WORKFLOW is None:
        _WORKFLOW = ThetaPromotionWorkflow()
    return _WORKFLOW
