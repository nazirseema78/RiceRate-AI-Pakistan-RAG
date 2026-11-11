"""Hybrid SQL + RAG chatbot. Numbers come from SQL; explanations come from retrieved documents."""
from __future__ import annotations

import re

from backend.services.analytics import prices as pa
from backend.services.rag import llm
from backend.services.rag.language import expand_query, tokens
from backend.services.rag.router import RoutedQuestion, route_question
from backend.services.rag.vectorstore import retrieve

CAUSAL = re.compile(r"because|due to|supported|linked|reason|cited|driver|as many|weaker|stronger|slower|ample|competition|demand|supply", re.I)
PRICED = re.compile(r"\d[\d,]*\s*(PKR|USD)/", re.I)
MAX_FACTS = 8

T = {
    "en": {"facts": "Observed facts (price database)", "docs": "From market reports (retrieved documents)",
           "interp": "Interpretation", "none": "No matching price observation is stored for this question.",
           "nodocs": "No relevant market report was found.",
           "synthetic": "Note: these figures are SYNTHETIC DEMO DATA (fictional), not real market prices.",
           "stale": "Note: no observation is dated today. The figures shown are the latest available, with their original dates - they are not today's rates.",
           "uncertain": "The evidence describes past prices only. Future market direction is uncertain.",
           "nollm": "(Retrieval-only answer: no LLM configured.)",
           "insufficient": "Current evidence is insufficient to state a market direction."},
    "ur": {"facts": "Darj shuda qeematein (price database)", "docs": "Market reports se (retrieved documents)",
           "interp": "Tashreeh (interpretation)", "none": "Is sawal ke liye koi mutabiq price observation database mein maujood nahi.",
           "nodocs": "Koi mutalliqa market report nahi mili.",
           "synthetic": "Note: yeh SYNTHETIC DEMO DATA hai (farzi), asal market rates nahi.",
           "stale": "Note: aaj ki tareekh ki koi observation maujood nahi. Neeche diye gaye rates aakhri dastiyab (latest available) hain, apni asal tareekh ke sath - yeh aaj ke rates nahi.",
           "uncertain": "Yeh shawahid sirf guzishta qeematon ke hain. Mustaqbil mein market ka rukh ghair yaqeeni hai.",
           "nollm": "(Sirf retrieval par mabni jawab: koi LLM configure nahi.)",
           "insufficient": "Mojooda shawahid market ka rukh batane ke liye nakafi hain."},
}
DIRECTION_UR = {"Rising": "Barh raha (Rising)", "Falling": "Kam ho raha (Falling)", "Stable": "Mustahkam (Stable)",
                "Mixed": "Mila jula (Mixed)", "Insufficient Data": "Nakafi data (Insufficient Data)"}


def _match(r: dict, rq: RoutedQuestion) -> bool:
    if rq.product_type and r.get("product_type") != rq.product_type:
        return False
    if rq.variety:
        hay = f"{r.get('variety', '')} {r.get('product_name', '')}".lower()
        if rq.variety not in hay:
            return False
    return True


def _price_line(r: dict) -> str:
    return (f"{r['product_name']} ({r['grade']}) - {r['city']}: {r['price']:,.0f} {r['original_unit']}"
            f" [{r['price_category']}; observed {r['observation_date']}; {r['data_label']}; source: {r['source_name']}]")


def _structured(rq: RoutedQuestion) -> tuple[list[str], list[dict], list[str], dict]:
    """Return (fact lines, source refs, interpretation lines, flags)."""
    facts, sources, interp = [], [], []
    flags = {"synthetic": False, "stale": False, "insufficient": False}
    L = T[rq.language]

    def add_src(name, doc, date, synthetic, kind="price_db"):
        sources.append({"type": kind, "name": name, "document": doc, "date": date,
                        "label": "SYNTHETIC DEMO DATA" if synthetic else "VERIFIED/IMPORTED SOURCE"})
        flags["synthetic"] |= bool(synthetic)

    if "quotation" in rq.intents and ("Karachi" in rq.cities or not rq.cities):
        qs = [q for q in pa.broker_quotations(valid_only=False) if _match(q, rq)]
        valid = [q for q in qs if q["is_valid"]]
        show = (valid or qs)[:MAX_FACTS]
        if qs and not valid:
            facts.append("No currently valid buyer quotation; showing the most recent expired quotations:"
                         if rq.language == "en" else "Koi mojooda valid buyer quotation nahi; aakhri expired quotations:")
        for q in show:
            facts.append(f"{q['product_name']} ({q['grade']}) - {q['buyer']}: {q['price']:,.0f} {q['unit']}, "
                         f"{q['quantity_mt']:.0f} MT, {q['delivery_terms']} [quoted {q['quoted_at'][:10]}, valid until "
                         f"{q['valid_until']} - {q['status']}; {'SYNTHETIC DEMO DATA' if q['is_synthetic'] else q['verification_status']}]")
            add_src(q["source_name"], q["source_document"], q["quoted_at"][:10], q["is_synthetic"])

    if "compare" in rq.intents:
        cities = [c for c in rq.cities if c != "Karachi"] or None
        cmp = pa.compare_markets(cities=cities)
        rows = [c for c in cmp["comparisons"] if _match(c, rq)]
        type_order = {"rice": 0, "broken_rice": 1, "paddy": 2}
        rows.sort(key=lambda c: (type_order.get(c["product_type"], 3), c["product_name"], c["city"]))
        for c in rows[:MAX_FACTS]:
            if c["valid"]:
                facts.append(f"{c['product_name']} ({c['grade']}): Karachi {c['karachi_normalized']:,.2f} vs {c['city']} "
                             f"{c['city_normalized']:,.2f} {c['normalized_unit']} -> difference {c['difference']:+,.2f} "
                             f"{c['normalized_unit']} ({c['difference_pct']:+.2f}%) [{c['city']} {c['city_date']}, Karachi "
                             f"{c['karachi_date']}; {'SYNTHETIC DEMO DATA' if c['is_synthetic'] else 'live/imported'}]")
            else:
                facts.append(f"{c['product_name']} {c['city']} vs Karachi: {c['note']}")
            for s in c["sources"]:
                add_src(s, "market_prices", c["city_date"], c["is_synthetic"])
        if rows:
            interp.append("Karachi prices normally include freight, handling and trader margin over Lower Punjab mill-gate prices; "
                          "only identical products and grades were compared, after converting PKR/40kg to PKR/kg."
                          if rq.language == "en" else
                          "Karachi ke rates mein aam tor par freight, handling aur trader margin shamil hota hai; sirf aik jaisi "
                          "products aur grades ka muqabla kiya gaya (PKR/40kg ko PKR/kg mein convert kar ke).")
        else:
            flags["insufficient"] = True

    if "trend" in rq.intents:
        w = rq.window_days if rq.window_days in (7, 15, 30) else 7
        ch = [c for c in pa.price_changes(windows=(w,)) if _match(c, rq)
              and (not rq.cities or c["city"] in rq.cities)
              # domestic questions exclude export series (e.g. "FOB Karachi") and vice versa
              and ((c["region"] == "International") == rq.international)]
        ch.sort(key=lambda c: (c["city"] != "Multan", c["product_name"], c["city"]))
        labels = []
        for c in ch[:MAX_FACTS]:
            pct = c[f"change_{w}d_pct"]
            lab = c[f"direction_{w}d"]
            labels.append(lab)
            if pct is None:
                facts.append(f"{c['product_name']} - {c['city']}: insufficient data for a {w}-day comparison "
                             f"(latest {c['latest_price']:,.0f} {c['unit']} on {c['latest_date']})")
            else:
                facts.append(f"{c['product_name']} - {c['city']}: {c['latest_price']:,.0f} {c['unit']} on {c['latest_date']} vs "
                             f"{c[f'base_{w}d_date']} -> {pct:+.2f}% over {w} days ({lab}) "
                             f"[{'SYNTHETIC DEMO DATA' if c['is_synthetic'] else c['source_name']}]")
            add_src(c["source_name"], "historical_prices", c["latest_date"], c["is_synthetic"])
        overall = pa.aggregate_direction(labels) if labels else "Insufficient Data"
        if overall == "Insufficient Data":
            flags["insufficient"] = True
        lab = DIRECTION_UR.get(overall, overall) if rq.language == "ur" else overall
        interp.append((f"Observed {w}-day direction across the matching series: {lab}." if rq.language == "en"
                       else f"Mutabiq series ka {w} din ka mushahida shuda rukh: {lab}.") + " " + L["uncertain"])

    if ("latest" in rq.intents and not {"compare", "trend"} & set(rq.intents)) or (rq.international and not facts):
        f = {}
        if rq.international:
            f["region"] = "International"
        latest = [r for r in pa.latest_prices(**f) if _match(r, rq) and (not rq.cities or r["city"] in rq.cities)]
        if not rq.international and not rq.cities:
            latest = [r for r in latest if r["region"] in ("Lower Punjab", "Karachi")] or latest
        latest.sort(key=lambda r: (r["is_synthetic"], r["city"] != "Multan", r["product_type"], r["product_name"]))
        for r in latest[:MAX_FACTS]:
            facts.append(_price_line(r))
            add_src(r["source_name"], r["source_document"] or r["source_url"], r["observation_date"], r["is_synthetic"])
            flags["stale"] |= not r["is_today"]
        if rq.international and latest:
            interp.append("International prices are export (FOB) quotations or monthly benchmarks in USD/MT; they are not "
                          "directly equivalent to Pakistani domestic wholesale prices." if rq.language == "en" else
                          "International rates export (FOB) quotations ya monthly benchmarks (USD/MT) hain; yeh Pakistan ke "
                          "domestic wholesale rates ke barabar nahi.")
    if not facts:
        flags["insufficient"] = True
    return facts, sources, interp, flags


def _extract_sentences(chunks: list[dict], question: str, n: int = 3) -> list[str]:
    qt = set(tokens(expand_query(question))) - {"the", "a", "of", "in", "is", "and", "kya", "hai", "mein", "ka", "ki", "ke"}
    price_question = bool(re.search(r"rate|price|qeemat|bhao|quote", question, re.I))
    cands = []
    for rank, c in enumerate(chunks):
        if c.get("doc_type") in ("csv", "xlsx"):
            continue  # tables are used via SQL; prose is better for explanations
        for s in re.split(r"(?<=[.!?])\s+", c["text"].replace("\n", " ")):
            if len(s) < 40:
                continue
            score = len(qt & set(tokens(s))) + (2 if CAUSAL.search(s) else 0) - rank * 0.3
            if price_question and PRICED.search(s):
                score += 3
            cands.append((score, s.strip(), c))
    cands.sort(key=lambda x: x[0], reverse=True)
    out, seen = [], set()
    for score, s, c in cands:
        if s in seen or score <= 0:
            continue
        seen.add(s)
        out.append(f"{s} [{c['source']}, published {c.get('publication_date') or 'n/a'}, {c.get('data_label', '')}]")
        if len(out) >= n:
            break
    return out


NUM = re.compile(r"\d[\d,]*\.?\d*")


def _numbers_grounded(answer: str, evidence: str) -> bool:
    ev = {x.replace(",", "").rstrip(".") for x in NUM.findall(evidence)}
    for x in NUM.findall(answer):
        v = x.replace(",", "").rstrip(".")
        if len(v.replace(".", "")) >= 3 and v not in ev:
            return False
    return True


def answer_question(question: str, history: list[dict] | None = None) -> dict:
    question = question.strip()[:1000]
    rq = route_question(question)
    L = T[rq.language]
    facts, sources, interp, flags = ([], [], [], {"synthetic": False, "stale": False, "insufficient": False})
    if rq.route in ("structured", "hybrid"):
        facts, sources, interp, flags = _structured(rq)
    chunks = []
    if rq.route in ("rag", "hybrid") or not facts:
        chunks = retrieve(question)
        for c in chunks:
            sources.append({"type": "document", "name": c["source"], "document": c["source"], "date": c.get("publication_date") or "",
                            "page": c.get("page"), "score": c["score"], "label": c.get("data_label", "")})
            flags["synthetic"] |= bool(c.get("is_synthetic"))
    doc_lines = _extract_sentences(chunks, question) if chunks else []

    warnings = []
    if flags["synthetic"]:
        warnings.append(L["synthetic"])
    if flags["stale"]:
        warnings.append(L["stale"])
    if flags["insufficient"] and rq.route != "rag":
        warnings.append(L["insufficient"])

    context_text = "\n---\n".join(f"[{c['source']} | {c.get('publication_date')}] {c['text']}" for c in chunks)
    facts_text = "\n".join(facts)
    generated = llm.generate(question, facts_text, context_text, rq.language, history) if llm.llm_enabled() else None
    used_llm = False
    if generated and _numbers_grounded(generated, facts_text + "\n" + context_text):
        body, used_llm = generated, True
    else:
        if generated:
            warnings.append("LLM answer discarded because it contained numbers not found in the sources.")
        parts = []
        if rq.route != "rag" or facts:
            parts.append(f"**{L['facts']}:**\n" + ("\n".join(f"- {f}" for f in facts) if facts else f"- {L['none']}"))
        if chunks:
            parts.append(f"**{L['docs']}:**\n" + ("\n".join(f"- {d}" for d in doc_lines) if doc_lines else f"- {L['nodocs']}"))
        if rq.route != "structured" and "explain" in rq.intents and L["uncertain"] not in " ".join(interp):
            interp.append(L["uncertain"])
        if interp:
            parts.append(f"**{L['interp']}:**\n" + "\n".join(f"- {i}" for i in interp))
        body = "\n\n".join(parts)
        if llm.llm_enabled() is False:
            body += f"\n\n_{L['nollm']}_"
    if warnings:
        body += "\n\n" + "\n".join(f"> {w}" for w in warnings)
    # de-duplicate sources
    uniq, seen = [], set()
    for s in sources:
        key = (s["type"], s["name"], s["document"], s["date"])
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return {"answer": body, "language": rq.language, "route": rq.route, "intents": rq.intents,
            "entities": {"cities": rq.cities, "product_type": rq.product_type, "variety": rq.variety, "window_days": rq.window_days,
                         "international": rq.international},
            "facts": facts, "sources": uniq[:15], "retrieved_chunks": [{k: c[k] for k in ("source", "score", "text")} for c in chunks],
            "used_llm": used_llm, "warnings": warnings, "contains_synthetic": flags["synthetic"]}
