"""Real-data evaluation — question compiler (paper Phase 2).

Maps a real forecasting question to an executable predicate over the engine's
simulated paths, or REFUSES with a reason code. Precision over recall: a
question compiles only when its semantics are unambiguously expressible over
state the simulator actually models (quarterly paths of oil price, global
growth, global inflation). Everything else is excluded with a taxonomy that
is itself a paper result (what fraction of real-world geopolitical questions
admits mechanistic treatment at all).

Families compiled here (pure path predicates):
  PRICE_THRESHOLD   Brent/WTI/crude spot above|below $X within a window
  MACRO_THRESHOLD   global inflation|growth above|below X% within a window

Exclusion reason codes (kept stable — they appear in the paper's Table 1):
  INSTITUTIONAL_EVENT   policy/announcement/legal events, no state variable
  COUNTRY_CHANNEL       country-specific series the engine does not model
  SUB_QUARTER_WINDOW    window shorter than one simulation quarter
  HAZARD_FAMILY         conflict-event clock (compiled in Phase 2b, not here)
  UNPARSEABLE_WINDOW    no confident deadline/window could be extracted
  NON_MECHANISTIC       everything else (entertainment, sports, misc.)
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np

# --------------------------------------------------------------------------
# window extraction
# --------------------------------------------------------------------------
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

_D_FULL = r"(?:(?P<d>\d{1,2})\s+)?(?P<mon>[A-Za-z]{3,9})\.?,?\s+(?P<y>\d{4})"     # 1 May 2016 / May 2016
_D_US   = r"(?P<mon2>[A-Za-z]{3,9})\.?\s+(?P<d2>\d{1,2}),\s*(?P<y2>\d{4})"        # Jan 1, 2020


def _mk_date(day, mon, year, end_of: bool = False) -> date | None:
    m = _MONTHS.get(str(mon).lower())
    if not m:
        return None
    y = int(year)
    if day is None:
        day = calendar.monthrange(y, m)[1] if end_of else 1
    return date(y, m, min(int(day), calendar.monthrange(y, m)[1]))


def extract_window(text: str, publish: datetime) -> tuple[date, date, str] | None:
    """Return (start, end, kind) for the question's event window, or None.
    kind is 'by' (from publish to deadline) or 'between' (explicit range)."""
    t = " ".join(text.split())
    p0 = publish.date()

    m = re.search(rf"[Bb]etween\s+(?:the\s+)?{_D_FULL}\s+and\s+", t)
    if m:
        m2 = re.search(rf"\s+and\s+(?:the\s+)?{_D_FULL}", t[m.start():])
        if m2:
            d1 = _mk_date(m.group("d"), m.group("mon"), m.group("y"))
            d2 = _mk_date(m2.group("d"), m2.group("mon"), m2.group("y"), end_of=True)
            if d1 and d2 and d1 < d2:
                return d1, d2, "between"

    m = re.search(r"[Bb]etween\s+(?P<d1>\d{1,2})\s+(?P<mon>[A-Za-z]{3,9})\s+and\s+"
                  r"(?P<d2>\d{1,2})\s+(?P<mon2>[A-Za-z]{3,9})\s+(?P<y>\d{4})", t)
    if m:  # "between 6 June and 8 September 2018"
        d1 = _mk_date(m.group("d1"), m.group("mon"), m.group("y"))
        d2 = _mk_date(m.group("d2"), m.group("mon2"), m.group("y"), end_of=True)
        if d1 and d2 and d1 < d2:
            return d1, d2, "between"

    for pat, end_of in ((rf"(?:[Bb]efore|[Bb]y)\s+(?:the\s+)?{_D_FULL}", False),
                        (rf"(?:[Bb]efore|[Bb]y)\s+{_D_US}", False)):
        m = re.search(pat, t)
        if m:
            g = m.groupdict()
            d = _mk_date(g.get("d") or g.get("d2"), g.get("mon") or g.get("mon2"),
                         g.get("y") or g.get("y2"), end_of=end_of)
            if d:
                return p0, d, "by"

    m = re.search(r"[Bb]y\s+(?:the\s+)?end\s+of\s+(?P<y>\d{4})", t) or \
        re.search(r"[Bb]efore\s+(?P<y>\d{4})\b", t) or \
        re.search(r"[Bb]y\s+(?:year[- ]end\s+)?(?P<y>\d{4})\b", t)
    if m:
        y = int(m.group("y"))
        end = date(y, 12, 31) if "end" in m.group(0).lower() or "by" in m.group(0).lower() \
            else date(y - 1, 12, 31)          # "before 2020" = through end-2019
        return p0, end, "by"

    m = re.search(r"[Bb]y\s+the\s+end\s+of\s+the\s+year", t)
    if m:
        return p0, date(p0.year, 12, 31), "by"

    m = re.search(r"\b[Ii]n\s+(?P<y>\d{4})\b", t)
    if m:                                     # "In 2016 will ..."
        y = int(m.group("y"))
        return date(y, 1, 1), date(y, 12, 31), "between"
    return None


# --------------------------------------------------------------------------
# compiled question
# --------------------------------------------------------------------------
@dataclass
class Compiled:
    family: str                               # PRICE_THRESHOLD | MACRO_THRESHOLD
    variable: str                             # 'oil' | 'inflation' | 'growth'
    direction: str                            # 'above' | 'below'
    threshold: float
    window: tuple[date, date]
    kind: str                                 # 'by' | 'between'

    def quarters(self, asof: date, dt_quarters: float = 0.25) -> tuple[int, int]:
        """Map the window to inclusive quarter indices of a sim starting at
        `asof`. Quarter k spans [asof + k*3mo, asof + (k+1)*3mo), so a date
        maps to floor(days / quarter-length) — round() would leak the window
        into a quarter it never touches."""
        qlen = 365.25 * dt_quarters
        def qi(d: date) -> int:
            return max(0, int((d - asof).days / qlen))
        q0, q1 = qi(self.window[0]), qi(self.window[1])
        return q0, max(q0, q1)

    def evaluate(self, sim: dict, asof: date) -> float:
        """Probability under the ensemble: fraction of paths where the
        variable crosses the threshold inside the window."""
        arr = np.asarray(sim[self.variable])              # (N paths, Q quarters)
        q0, q1 = self.quarters(asof)
        q1 = min(q1, arr.shape[1] - 1)
        if q0 > q1 or q0 >= arr.shape[1]:
            return 0.0
        seg = arr[:, q0:q1 + 1]
        hit = (seg >= self.threshold) if self.direction == "above" else (seg <= self.threshold)
        return float(hit.any(axis=1).mean())


@dataclass
class Excluded:
    reason: str
    detail: str = ""


# --------------------------------------------------------------------------
# family parsers
# --------------------------------------------------------------------------
_PRICE_CTX = r"(?:brent|wti|crude)"
_INSTITUTIONAL = (r"opec|announce|legislat|congress|ban\b|pipeline|company|employ|"
                  r"agree|approve|default|sanction|deal\b|output\b|production|spill|"
                  r"tranche|committee|rate on excess|mortgage")


def _parse_price(text: str, publish: datetime) -> Compiled | Excluded | None:
    t = text.lower()
    if not re.search(_PRICE_CTX, t):
        return None
    m = re.search(r"\$ ?(\d+(?:\.\d+)?)", t)
    if not m:
        return Excluded("INSTITUTIONAL_EVENT", "commodity mention without price level") \
            if re.search(_INSTITUTIONAL, t) else None
    thr = float(m.group(1))
    direction = "below" if re.search(r"dip|below|under|fall|less than", t) else \
                "above" if re.search(r"above|exceed|over|more than|rise|top", t) else None
    if direction is None:
        return Excluded("UNPARSEABLE_WINDOW", "price level without direction")
    win = extract_window(text, publish)
    if win is None:
        return Excluded("UNPARSEABLE_WINDOW", "no deadline found")
    d1, d2, kind = win
    if (d2 - d1).days < 80:
        return Excluded("SUB_QUARTER_WINDOW", f"{(d2 - d1).days}d window")
    return Compiled("PRICE_THRESHOLD", "oil", direction, thr, (d1, d2), kind)


def _parse_macro(text: str, publish: datetime) -> Compiled | Excluded | None:
    t = text.lower()
    var = "inflation" if "inflation" in t else \
          "growth" if re.search(r"gdp growth|growth rate|economic growth", t) else None
    if var is None:
        return None
    if re.search(r"\b(us|u\.s\.|egypt|china|india|japan|germany|uk|argentina|turkey|"
                 r"brazil|russia|federal|fomc|mortgage)\b", t):
        return Excluded("COUNTRY_CHANNEL", "country-specific series (engine is global)")
    m = re.search(r"(\d+(?:\.\d+)?) ?(?:%|percent)", t)
    if not m:
        return Excluded("UNPARSEABLE_WINDOW", "no threshold percent")
    thr = float(m.group(1))
    direction = "below" if re.search(r"below|under|less than|fall", t) else "above"
    win = extract_window(text, publish)
    if win is None:
        return Excluded("UNPARSEABLE_WINDOW", "no deadline found")
    d1, d2, kind = win
    if (d2 - d1).days < 80:
        return Excluded("SUB_QUARTER_WINDOW", f"{(d2 - d1).days}d window")
    return Compiled("MACRO_THRESHOLD", var, direction, thr, (d1, d2), kind)


_CONFLICT_EVENT = (r"airstrike|air strike|armed conflict|military action|confrontation|"
                   r"ceasefire|invasion|deploy|troops|casualt|clash|attack")


def compile_question(text: str, publish: datetime) -> Compiled | Excluded:
    """Compile one question or return an Excluded with a stable reason code."""
    for parser in (_parse_price, _parse_macro):
        r = parser(text, publish)
        if r is not None:
            return r
    t = text.lower()
    if re.search(_CONFLICT_EVENT, t):
        return Excluded("HAZARD_FAMILY", "conflict-event clock (Phase 2b)")
    if re.search(_INSTITUTIONAL, t):
        return Excluded("INSTITUTIONAL_EVENT")
    return Excluded("NON_MECHANISTIC")


def coverage_report(questions) -> dict:
    """Compile every question; return counts + the compiled/excluded lists.
    `questions` iterates objects with .question and .publish_time."""
    compiled, excluded = [], []
    for q in questions:
        r = compile_question(q.question, q.publish_time)
        (compiled if isinstance(r, Compiled) else excluded).append((q, r))
    counts: dict[str, int] = {}
    for _, r in excluded:
        counts[r.reason] = counts.get(r.reason, 0) + 1
    return {"n": len(compiled) + len(excluded), "compiled": compiled,
            "excluded": excluded, "n_compiled": len(compiled),
            "by_family": {f: sum(1 for _, c in compiled if c.family == f)
                          for f in {c.family for _, c in compiled}},
            "exclusions": dict(sorted(counts.items(), key=lambda kv: -kv[1]))}
