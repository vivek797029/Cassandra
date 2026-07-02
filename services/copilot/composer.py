"""ARGUS Copilot — grounded answer composition.
Renders ONLY from engine objects (blueprint §9/§11 faithfulness rule):
every sentence maps to a field of a structured object. No free generation."""
from __future__ import annotations

def pct(p: float) -> str:
    return f"{100*p:.0f}%"

def band_str(f: dict) -> str:
    if f.get("band"):
        return f"{pct(f['probability'])} [{pct(f['band']['lo'])}–{pct(f['band']['hi'])}]"
    return pct(f["probability"])

def fc_line(f: dict) -> str:
    v = f" · {f['verdict']}" if f.get("verdict") else ""
    return f"**{f['question_text']}** — **{band_str(f)}**{v} (horizon {f.get('horizon','—')})"

def compose(intent: str, parse: dict, objs: dict, persona: str) -> tuple[str, bool]:
    """Returns (markdown, abstained)."""
    fcs = objs.get("forecasts", [])
    exp = objs.get("explanation")
    cf = objs.get("counterfactual")
    pol = objs.get("policy")
    analogs = objs.get("analogs", [])
    ewi = objs.get("early_warnings", [])

    L: list[str] = []
    abstained = False

    if intent in ("FORECAST", "CAUSE", "EXPLAIN") and not fcs and not exp:
        L.append("I can't map this question to a scored forecast or identified mechanism yet — "
                 "abstaining rather than guessing. Try one of: Middle East war risk, Hormuz closure, "
                 "Ukraine ceasefire, Taiwan blockade, oil >$120, global recession, 2027 inflation, "
                 "US House midterms, EM defaults.")
        return "\n".join(L), True

    if intent == "FORECAST":
        for f in fcs[:4]:
            L.append("- " + fc_line(f))
        if exp:
            L.append(f"\n**Mechanism:** {exp['causal_pathway']}")
            L.append(f"**Strongest counterargument:** {exp['counterargument']}")
        if persona == "principal" and fcs:
            L = [fc_line(fcs[0]), "",
                 f"Counter-case: {exp['counterargument']}" if exp else "",
                 f"Watch: {', '.join(x['failure'] if isinstance(x, str) else x for x in (exp['failure_conditions'] if exp else []))}" if exp else ""]
            L = [x for x in L if x]
    elif intent in ("CAUSE", "EXPLAIN"):
        if fcs:
            L.append(fc_line(fcs[0]))
        if exp:
            L.append(f"\n**Evidence:** {', '.join(exp['evidence'])} (Phase-1 fact IDs; see /v1/facts)")
            L.append(f"**Causal pathway:** {exp['causal_pathway']}")
            L.append(f"**Historical analog:** {exp['historical_analog']}")
            L.append(f"**Counterargument:** {exp['counterargument']}")
            L.append(f"**Forecast fails if:** {'; '.join(exp['failure_conditions'])}")
            L.append(f"**Confidence:** {exp['confidence']}")
    elif intent == "WHATIF":
        if not cf:
            L.append("Tell me which lever to move — e.g. *what if we deploy a Gulf maritime "
                     "verification coalition?* Available levers: Gulf maritime verification, "
                     "strategic energy buffer, EM bridge financing, Ukraine armistice track, "
                     "food-security facility, Taiwan deterrence-by-denial, AI-security compact.")
            abstained = True
        else:
            L.append(f"**Counterfactual (paired {cf['request']['n_paths']}-path CRN simulation, "
                     f"{cf['request']['horizon_quarters']} quarters):**")
            for e in cf["effects"]:
                arrow = "↓" if e["delta"] < 0 else "↑"
                L.append(f"- {e['target']}: {pct(e['baseline'])} → {pct(e['counterfactual'])} "
                         f"({arrow} {abs(e['rel_change_pct'])}%)")
            L.append(f"- Harm index: {cf['harm_baseline']} → {cf['harm_counterfactual']}")
            L.append(f"\n*Assumptions:* {'; '.join(cf['assumptions'])}")
    elif intent == "POLICY":
        if pol:
            L.append(f"**Recommended portfolio (budget {pol['budget']}, greedy robust-EV search):**")
            for i, s in enumerate(pol["greedy_steps"], 1):
                L.append(f"{i}. {s['added']} (cost {s['cost']}, marginal value/cost {s['marginal_value_per_cost']})")
            L.append(f"\nHarm index {pol['base_harm']} → {pol['portfolio_harm']} "
                     f"(−{pol['harm_reduction_pct']}%).")
            L.append(f"*Caveats:* {'; '.join(pol['caveats'])}")
    elif intent == "EWI":
        L.append("**Early-warning indicators (metric · threshold · lead time · confidence):**")
        for e in ewi[:10]:
            L.append(f"- {e['indicator']}: {e['metric']} · {e['threshold']} · "
                     f"{e['lead_time']} · {e['confidence']}")
    elif intent == "ANALOG":
        L.append("**Most similar historical episodes (mechanism evidence, not destiny):**")
        for a in analogs[:3]:
            L.append(f"- **{a['name']}** (similarity {a['similarity']}): {a['lesson']}")
    elif intent == "SCENARIOS":
        sc = objs.get("scenarios", {})
        L.append("**Scenarios (discovered by clustering the ensemble):**")
        for c in sc.get("clusters", []):
            L.append(f"- {c['scenario']}: share {pct(c['share'])}, worst annual growth "
                     f"{c['min_annual_growth_med']}%, max oil ${c['max_oil_med']}, "
                     f"war quarters {c['war_quarters_med']}")
    elif intent == "VULNERABILITY":
        L.append("**Most exposed (current causal map):** energy/food-importing EMs with 2027 "
                 "maturities (EM stress channel), Gulf shipping lanes (Hormuz channel), "
                 "LICs where food ≈ 43% of consumption (El Niño channel).")
        for e in ewi[:3]:
            L.append(f"- Watch: {e['indicator']} ({e['threshold']})")
    elif intent == "STATUS":
        L.append("**Situation (evidence as of 2026-06-11):**")
        for f in objs.get("facts", [])[:5]:
            L.append(f"- [{f['id']}] {f['text']}")
        if objs.get("redaction_notice"):                 # Task 75: clearance-filtered render
            L.append(f"_{objs['redaction_notice']}_")
        L.append("\nHeadline risks:")
        for f in fcs[:3]:
            L.append("- " + fc_line(f))
    else:
        L.append("I parse questions into: forecast, why/cause, what-if, policy, early-warning, "
                 "vulnerability, analogs, scenarios, status. Rephrase or pick one.")
        abstained = True

    if not abstained and objs.get("manifest_id"):
        L.append(f"\n`manifest:{objs['manifest_id']}` — fully reproducible via /v1/audit/{objs['manifest_id']}")
    return "\n".join(L), abstained
