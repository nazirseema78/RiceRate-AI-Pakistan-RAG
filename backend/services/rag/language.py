"""Language detection (English / Pakistani Urdu, incl. Roman Urdu) and query normalisation."""
from __future__ import annotations

import re

URDU_SCRIPT = re.compile(r"[؀-ۿ]")
ROMAN_URDU_MARKERS = {
    "kya", "hai", "hain", "mein", "main", "ka", "ki", "ke", "ko", "aaj", "aj", "kyun", "kyon", "farq", "barha", "barh",
    "kam", "hua", "huay", "pichlay", "pichle", "din", "rate", "qeemat", "keemat", "bhao", "chawal", "dhaan", "dhan",
    "do", "batao", "bataen", "kitna", "kitni", "aur", "rahay", "rahe", "girnay", "signals", "hafta", "mahina", "wajah",
    "toota", "tota", "kharidar", "dein", "sakta", "abhi", "kal", "taaza",
}
STRONG_MARKERS = {"kya", "hai", "hain", "mein", "aaj", "kyun", "kyon", "farq", "pichlay", "pichle", "batao", "chawal",
                  "dhaan", "rahay", "girnay", "wajah", "kitna", "kitni", "qeemat", "bhao", "toota", "hua", "ka", "ke", "ki"}

# Roman Urdu / Urdu -> English hints used to expand the retrieval query (embedding models are English-centric)
GLOSSARY = {
    "aaj": "today latest", "aj": "today latest", "dhaan": "paddy", "dhan": "paddy", "munji": "paddy", "chawal": "rice",
    "toota": "broken rice", "tota": "broken rice", "farq": "difference compare", "barha": "increase rising",
    "barh": "increase rising", "kam": "decrease falling", "gira": "fall falling", "girnay": "falling decline",
    "kyun": "why reason", "kyon": "why reason", "wajah": "reason cause", "qeemat": "price", "keemat": "price",
    "bhao": "price rate", "khabar": "news", "kharidar": "buyer quotation", "hafta": "week", "pichlay": "last past",
    "pichle": "last past", "din": "days", "bahar": "export international", "aalmi": "international global",
    "چاول": "rice", "دھان": "paddy", "قیمت": "price",
    "آج": "today", "کراچی": "Karachi", "ملتان": "Multan",
}


def tokens(text: str) -> list[str]:
    return re.findall(r"[\w\-]+", text.lower())


def detect_language(text: str) -> str:
    """Return 'ur' for Urdu script or Roman Urdu, else 'en'."""
    if URDU_SCRIPT.search(text):
        return "ur"
    toks = tokens(text)
    strong = sum(t in STRONG_MARKERS for t in toks)
    weak = sum(t in ROMAN_URDU_MARKERS for t in toks)
    return "ur" if strong >= 1 and weak >= 2 else "en"


def expand_query(text: str) -> str:
    extra = [GLOSSARY[t] for t in tokens(text) if t in GLOSSARY]
    for k, v in GLOSSARY.items():
        if URDU_SCRIPT.search(k) and k in text:
            extra.append(v)
    return text + (" " + " ".join(extra) if extra else "")
