"""Embeddings + ChromaDB vector index (via LangChain)."""
from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from datetime import datetime
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from backend.config import get_settings
from backend.database.db import get_conn
from backend.services.rag.documents import chunk_documents, load_directory
from backend.services.rag.language import expand_query

log = logging.getLogger(__name__)
_lock = threading.Lock()
_init_lock = threading.RLock()  # one model/store load even when many requests arrive at once
_store = None
_embeddings: Embeddings | None = None


class HashEmbeddings(Embeddings):
    """Deterministic offline bag-of-words hashing embeddings.

    Used for automated tests and as a fallback when the Sentence Transformers model cannot be
    downloaded. Retrieval quality is lower than a real embedding model.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        toks = re.findall(r"\w+", text.lower())
        for t in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
            h = int(hashlib.md5(t.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embeddings() -> Embeddings:
    global _embeddings
    if _embeddings is not None:
        return _embeddings
    with _init_lock:
        if _embeddings is None:
            _embeddings = _load_embeddings()
    return _embeddings


def _load_embeddings() -> Embeddings:
    s = get_settings()
    if s.embedding_backend == "hash":
        return HashEmbeddings()
    try:
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name=s.embedding_model, model_kwargs={"device": "cpu"},
                                     encode_kwargs={"normalize_embeddings": True})
    except Exception as e:  # offline / model download failure
        log.error("Sentence Transformers model unavailable (%s) - falling back to HashEmbeddings", e)
        return HashEmbeddings()


def embedding_name() -> str:
    e = get_embeddings()
    return "hash-embeddings (offline fallback)" if isinstance(e, HashEmbeddings) else get_settings().embedding_model


def get_store():
    global _store
    if _store is not None:
        return _store
    with _init_lock:
        if _store is None:
            from langchain_chroma import Chroma

            s = get_settings()
            Path(s.chroma_path).mkdir(parents=True, exist_ok=True)
            _store = Chroma(collection_name=s.chroma_collection, embedding_function=get_embeddings(),
                            persist_directory=str(s.chroma_path), collection_metadata={"hnsw:space": "cosine"})
    return _store


def reset_cache() -> None:
    global _store, _embeddings
    with _init_lock:
        _store, _embeddings = None, None


def index_count() -> int:
    try:
        return get_store()._collection.count()
    except Exception:
        return 0


def build_index(directory: Path | None = None, rebuild: bool = False) -> dict:
    """Load -> clean -> chunk -> embed -> store. Idempotent: chunk ids are content hashes."""
    s = get_settings()
    directory = Path(directory or s.documents_dir)
    with _lock:
        store = get_store()
        if rebuild:
            existing = store.get(include=[])["ids"]
            if existing:
                store.delete(ids=existing)
        docs = load_directory(directory)
        chunks = chunk_documents(docs, s.chunk_size, s.chunk_overlap)
        ids = [c.metadata["chunk_id"] for c in chunks]
        have = set(store.get(ids=ids, include=[])["ids"]) if ids else set()
        new = [(c, i) for c, i in zip(chunks, ids) if i not in have]
        for start in range(0, len(new), 64):
            batch = new[start:start + 64]
            store.add_documents([c for c, _ in batch], ids=[i for _, i in batch])
        now = datetime.now().isoformat(timespec="seconds")
        per_file: dict[str, list[Document]] = {}
        for c in chunks:
            per_file.setdefault(c.metadata["source"], []).append(c)
        with get_conn() as conn:
            for fname, cs in per_file.items():
                m = cs[0].metadata
                conn.execute("""INSERT INTO source_documents (filename, doc_type, publication_date, sha256, chunk_count, is_synthetic, indexed_at)
                                VALUES (?,?,?,?,?,?,?) ON CONFLICT(filename) DO UPDATE SET sha256=excluded.sha256,
                                chunk_count=excluded.chunk_count, publication_date=excluded.publication_date, indexed_at=excluded.indexed_at""",
                             (fname, m["doc_type"], m.get("publication_date") or None, m["sha256"], len(cs), int(m["is_synthetic"]), now))
    return {"documents": len(per_file), "pages_or_blocks": len(docs), "chunks": len(chunks), "added": len(new),
            "embedding_model": embedding_name(), "collection": s.chroma_collection}


def ensure_index() -> None:
    if index_count() == 0:
        log.info("Vector index empty - building from %s", get_settings().documents_dir)
        build_index()


def retrieve(query: str, k: int | None = None, filter_meta: dict | None = None) -> list[dict]:
    from backend.services.provider_settings import get_accuracy

    acc = get_accuracy()
    k = k or acc["retrieval_k"]
    store = get_store()
    results = store.similarity_search_with_score(expand_query(query), k=k, filter=filter_meta)
    out = []
    for doc, distance in results:
        score = round(1.0 - float(distance), 4)
        if score < acc["min_retrieval_score"]:
            continue  # too dissimilar: off-topic text makes answers less accurate
        out.append({"text": doc.page_content, "score": score, **doc.metadata})
    return out
