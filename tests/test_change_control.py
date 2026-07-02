"""Task 99 — change-control freeze gate: blocks releases during a freeze unless
emergency/CAB-approved; allows outside freeze."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "change_control", os.path.join(os.path.dirname(__file__), "..", "scripts", "change_control.py"))
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_windows_loaded():
    w = cc.load_windows()
    assert w and all("start" in x and "end" in x for x in w)


def test_freeze_blocks_unless_override():
    # 2026-12-20 falls inside the year-end freeze
    assert cc.check("2026-12-20")["allowed"] is False
    assert cc.check("2026-12-20", emergency=True)["allowed"] is True
    assert cc.check("2026-12-20", cab_approved=True)["allowed"] is True


def test_outside_freeze_allowed():
    r = cc.check("2026-09-01")
    assert r["in_freeze"] is False and r["allowed"] is True


def test_doc_present():
    p = os.path.join(ROOT, "docs", "process", "change-control.md")
    t = open(p, encoding="utf-8").read().lower()
    assert "cab" in t and "freeze" in t and "enforced in ci" in t


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
