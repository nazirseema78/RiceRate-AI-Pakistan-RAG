from pathlib import Path

from backend.services.rag.chatbot import _numbers_grounded, answer_question
from backend.services.rag.documents import chunk_documents, clean_text, load_directory
from backend.services.rag.language import detect_language, expand_query
from backend.services.rag.router import route_question
from backend.services.rag.vectorstore import retrieve

DOCS = Path(__file__).resolve().parents[1] / "data" / "documents"


def test_all_document_types_load_with_metadata():
    docs = load_directory(DOCS)
    types = {d.metadata["doc_type"] for d in docs}
    assert {"pdf", "csv", "txt", "xlsx"} <= types
    for d in docs:
        assert d.metadata["source"] and d.metadata["is_synthetic"] is True
        assert d.metadata["data_label"] == "SYNTHETIC DEMO DATA"


def test_cleaning_and_chunking():
    assert clean_text("rice   price\n\n\nhyph-\nenated") == "rice price\nhyphenated"
    chunks = chunk_documents(load_directory(DOCS), 700, 120)
    assert len(chunks) > 20
    assert all(len(c.page_content) <= 700 for c in chunks)
    assert len({c.metadata["chunk_id"] for c in chunks}) == len(chunks)


def test_index_built(seeded):
    assert seeded["index"]["chunks"] > 20 and seeded["index"]["documents"] >= 10


def test_retrieval_returns_relevant_source(seeded):
    hits = retrieve("Thai Vietnamese 5% broken export quotations international", k=5)
    assert hits and all("source" in h and "score" in h for h in hits)
    assert any(h["source"] in ("International_Rice_Price_Report.pdf", "Global_Rice_Market_Commentary.txt") for h in hits)
    hits = retrieve("Karachi wholesale Sella rice report", k=5)
    assert any("Karachi" in h["source"] for h in hits)


def test_language_detection():
    assert detect_language("Aaj Multan mein 1121 paddy ka latest available rate kya hai?") == "ur"
    assert detect_language("What is the latest 1121 paddy rate in Multan?") == "en"
    assert detect_language("ملتان میں چاول کی قیمت") == "ur"
    assert "paddy" in expand_query("dhaan ka bhao")


def test_router():
    r = route_question("Aaj Multan mein 1121 paddy ka latest available rate kya hai?")
    assert r.route == "structured" and r.cities == ["Multan"] and r.product_type == "paddy" and r.variety == "1121"
    assert route_question("Karachi mein rice rates kyun change ho rahay hain?").route == "hybrid"
    assert route_question("Latest available rice market report ka summary do.").route in ("rag", "hybrid")
    r = route_question("Pichlay 15 din mein 1121 rice ka rate barha hai ya kam hua?")
    assert "trend" in r.intents and r.window_days == 15
    assert route_question("Aaj Punjab aur Karachi ke rice rates mein kya farq hai?").intents.count("compare") == 1


def test_structured_answer_uses_sql_with_dates_and_labels(seeded):
    res = answer_question("Aaj Multan mein 1121 paddy ka latest available rate kya hai?")
    assert res["language"] == "ur" and res["route"] == "structured"
    assert res["facts"] and all("Multan" in f and "observed" in f for f in res["facts"])
    assert "SYNTHETIC" in res["answer"]
    assert any(s["type"] == "price_db" for s in res["sources"])


def test_trend_answer_has_direction_and_uncertainty(seeded):
    res = answer_question("Pichlay 7 din mein 1121 rice ka rate barha hai ya kam hua?")
    assert any("over 7 days" in f for f in res["facts"])
    assert "ghair yaqeeni" in res["answer"]  # Urdu uncertainty statement


def test_hybrid_answer_has_facts_and_document_sources(seeded):
    res = answer_question("Why are Karachi rice rates changing?")
    assert res["route"] == "hybrid" and res["language"] == "en"
    assert any(s["type"] == "document" for s in res["sources"])
    assert "uncertain" in res["answer"].lower()


def test_quotation_answer(seeded):
    res = answer_question("Karachi mein broken rice ka latest verified quote kya hai?")
    assert res["facts"] and any("valid until" in f for f in res["facts"])


def test_unavailable_price_is_explained(seeded):
    res = answer_question("What is the latest paddy rate in Lahore?")
    assert not [f for f in res["facts"] if "Lahore" in f]
    assert "No matching price observation" in res["answer"] or "insufficient" in res["answer"].lower()


def test_numeric_grounding_guard():
    evidence = "1121 Basmati Paddy - Multan: 4,780 PKR/40kg observed 2026-11-10"
    assert _numbers_grounded("Multan 1121 paddy is 4,780 PKR/40kg (2026-11-10)", evidence)
    assert _numbers_grounded("The rate is 4,780 PKR/40kg", evidence)
    assert not _numbers_grounded("The rate is 5,100 PKR/40kg", evidence)
