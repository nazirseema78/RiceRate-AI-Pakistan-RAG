"""Question router: structured (SQL) vs market explanation (RAG) vs hybrid."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.services.rag.language import detect_language

CITY_PATTERNS = {
    "Multan": r"multan", "Muzaffargarh": r"muzaf+ar\s*g[ae]?r?h|muzafarghar", "Bahawalpur": r"bahawalpur|bwp",
    "Rahim Yar Khan": r"rahim\s*yar\s*khan|ryk", "Karachi": r"karachi|khi", "Lahore": r"lahore",
}
VARIETY_PATTERNS = {"1121": r"1121|kainat", "super basmati": r"super\s*basmati|\bsuper\b", "irri": r"irri|eri\b",
                    "386": r"\b386\b|pk-?386", "basmati": r"basmati"}
WORDS = {
    "compare": r"farq|difference|differ|compare|comparison|\bvs\.?\b|versus|muqabla|mukabla|between|gap",
    "trend": r"barh|barha|kam\s+hu|gir|increase|decrease|trend|change|pichl|last\s+\d+\s+days|\d+\s*din|week|hafta|direction|"
             r"signal|rise|rising|fall|falling|up or down|upar|neeche|mahina|month",
    "latest": r"\brate|price|qeemat|keemat|bhao|bhaav|latest|\baaj\b|\baj\b|today|current|abhi|taaza|kitn",
    "quotation": r"quote|quotation|buyer|kharidar|offer",
    "explain": r"kyun|kyon|\bwhy\b|reason|wajah|explain|because|sabab|signal",
    "news": r"news|khabar|update|report|summary|summar|briefing|commentary|halaat|situation",
    "international": r"international|global|world|thai|vietnam|india|export|bahar|aalmi|duniya|fob|usd|dollar",
}


@dataclass
class RoutedQuestion:
    question: str
    language: str
    route: str  # structured | rag | hybrid
    intents: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    product_type: str | None = None
    variety: str | None = None
    window_days: int = 7
    international: bool = False
    followup_of: str | None = None


def route_question(question: str) -> RoutedQuestion:
    q = question.lower()
    intents = [k for k, p in WORDS.items() if k != "international" and re.search(p, q)]
    cities = [c for c, p in CITY_PATTERNS.items() if re.search(p, q)]
    if re.search(r"paddy|dhaa?n|munji", q):
        ptype = "paddy"
    elif re.search(r"broken|toota|tota|tukda|kinki|b1\b", q):
        ptype = "broken_rice"
    elif re.search(r"sella|steam|chawal|finished|milled", q):
        ptype = "rice"
    else:
        ptype = None
    variety = next((v for v, p in VARIETY_PATTERNS.items() if re.search(p, q)), None)
    m = re.search(r"(\d{1,2})\s*(din|days?|day)", q)
    window = int(m.group(1)) if m else (30 if re.search(r"month|mahina|30", q) else 15 if "15" in q else 7)
    window = min(max(window, 1), 90)
    international = bool(re.search(WORDS["international"], q))
    if "explain" in intents:
        route = "hybrid"
    elif "news" in intents and ({"trend", "compare"} & set(intents) or international or cities or ptype or variety):
        route = "hybrid"
    elif "news" in intents:
        route = "rag"
    elif {"latest", "compare", "trend", "quotation"} & set(intents):
        route = "structured"
    else:
        route = "rag"
    return RoutedQuestion(question, detect_language(question), route, intents, cities, ptype, variety, window, international)
