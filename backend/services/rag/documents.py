"""Document loading, cleaning and chunking (LangChain). Supports PDF, TXT, CSV and Excel."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

SUPPORTED = {".pdf", ".txt", ".csv", ".xlsx", ".xls"}
SYNTHETIC_BANNER = re.compile(r"SYNTHETIC DEMONSTRATION DATA\s*-\s*FICTIONAL PRICES, NOT REAL MARKET QUOTATIONS\.?", re.I)
DATE_PATTERNS = [re.compile(p, re.I) for p in (r"Publication date:\s*(\d{4}-\d{2}-\d{2})", r"Week ending:\s*(\d{4}-\d{2}-\d{2})")]
ROWS_PER_CHUNK = 12


def _pub_date(text: str) -> str | None:
    for p in DATE_PATTERNS:
        m = p.search(text)
        if m:
            return m.group(1)
    return None


def _table_documents(df: pd.DataFrame, path: Path, sheet: str | None = None) -> list[Document]:
    """Turn a table into text blocks of N rows. Each block repeats the header so chunks stay self-explanatory."""
    df = df.fillna("")
    date_col = next((c for c in df.columns if "date" in str(c).lower() or str(c).lower().endswith("_at")), None)
    pub = str(max(df[date_col].astype(str)))[:10] if date_col is not None and len(df) else None
    series_cols = [c for c in ("product_name", "grade", "city", "unit", "price_category") if c in df.columns]
    if date_col is not None and "price" in df.columns and len(series_cols) >= 3 and len(df) > 4 * ROWS_PER_CHUNK:
        return _series_documents(df, path, date_col, series_cols, pub, sheet)
    # constant columns (e.g. data_label) are stated once in the header instead of on every row
    constant = {c: df[c].iloc[0] for c in df.columns if len(df) and df[c].nunique() == 1}
    cols = [c for c in df.columns if c not in constant]
    docs = []
    for start in range(0, len(df), ROWS_PER_CHUNK):
        block = df.iloc[start:start + ROWS_PER_CHUNK]
        lines = [f"Table {path.name}{' / ' + sheet if sheet else ''}, rows {start + 1}-{start + len(block)}. "
                 + "".join(f"{c}: {v}. " for c, v in constant.items()) + "Columns: " + " | ".join(map(str, cols))]
        for _, row in block.iterrows():
            lines.append(" | ".join(str(row[c]) for c in cols))
        docs.append(Document(page_content="\n".join(lines),
                             metadata={"source": path.name, "doc_type": path.suffix.lstrip(".").lower(), "sheet": sheet or "",
                                       "row_start": start + 1, "publication_date": pub or "", "page": 0}))
    return docs


def _series_documents(df: pd.DataFrame, path: Path, date_col: str, series_cols: list[str], pub: str | None,
                      sheet: str | None) -> list[Document]:
    """Long price tables: one Document per price series (product + grade + city + unit), newest dates first.

    Row blocks of a 1,700-row table would flood the vector index with near-identical chunks; a series
    document instead reads like a short report ("1121 Sella in Karachi: 2026-11-10 312, 2026-11-09 311 ...").
    """
    label = f" Data label: {df['data_label'].iloc[0]}." if "data_label" in df.columns else ""
    docs = []
    for key, g in df.groupby(series_cols, sort=True):
        g = g.sort_values(date_col, ascending=False)
        meta = dict(zip(series_cols, key if isinstance(key, tuple) else (key,)))
        title = (f"Price history from {path.name}: {meta.get('product_name', '')} ({meta.get('grade', '')}) in "
                 f"{meta.get('city', '')}, {meta.get('price_category', '')} price in {meta.get('unit', '')}.{label}")
        first, last = g.iloc[0], g.iloc[-1]
        summary = (f" Latest observation {str(first[date_col])[:10]}: {first['price']}. Earliest in file "
                   f"{str(last[date_col])[:10]}: {last['price']}.")
        points = "; ".join(f"{str(r[date_col])[:10]}: {r['price']}" for _, r in g.iterrows())
        docs.append(Document(page_content=f"{title}{summary}\nDaily observations (newest first): {points}",
                             metadata={"source": path.name, "doc_type": path.suffix.lstrip(".").lower(), "sheet": sheet or "",
                                       "row_start": 0, "publication_date": pub or "", "page": 0}))
    return docs


def load_document(path: Path) -> list[Document]:
    from langchain_community.document_loaders import PyPDFLoader, TextLoader

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        docs = PyPDFLoader(str(path)).load()
        full = " ".join(d.page_content for d in docs)
        for d in docs:
            d.metadata = {"source": path.name, "doc_type": "pdf", "page": int(d.metadata.get("page", 0)) + 1,
                          "publication_date": _pub_date(full) or "", "sheet": "", "row_start": 0}
        return docs
    if suffix == ".txt":
        docs = TextLoader(str(path), encoding="utf-8").load()
        for d in docs:
            d.metadata = {"source": path.name, "doc_type": "txt", "page": 1,
                          "publication_date": _pub_date(d.page_content) or "", "sheet": "", "row_start": 0}
        return docs
    if suffix == ".csv":
        return _table_documents(pd.read_csv(path), path)
    if suffix in (".xlsx", ".xls"):
        out = []
        for sheet, df in pd.read_excel(path, sheet_name=None).items():
            out += _table_documents(df, path, sheet)
        return out
    raise ValueError(f"Unsupported document type: {path.name}")


def clean_text(text: str) -> str:
    text = text.replace(" ", " ").replace("–", "-").replace("—", "-")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)      # re-join hyphenated line breaks
    text = SYNTHETIC_BANNER.sub(" ", text)             # banner is kept as metadata instead of in every chunk
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def load_directory(directory: Path) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in SUPPORTED:
            continue
        raw = path.read_bytes()
        loaded = load_document(path)
        joined = " ".join(d.page_content for d in loaded).upper()
        synthetic = "SYNTHETIC" in joined
        for d in loaded:
            d.page_content = clean_text(d.page_content)
            d.metadata["is_synthetic"] = synthetic
            d.metadata["data_label"] = "SYNTHETIC DEMO DATA" if synthetic else "UNVERIFIED DOCUMENT"
            d.metadata["sha256"] = hashlib.sha256(raw).hexdigest()
        docs += [d for d in loaded if d.page_content]
    return docs


def chunk_documents(docs: list[Document], chunk_size: int = 700, chunk_overlap: int = 120) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                                              separators=["\n\n", "\n", ". ", "; ", " ", ""])
    chunks = splitter.split_documents(docs)
    counters: dict[str, int] = {}
    for c in chunks:
        n = counters.get(c.metadata["source"], 0)
        counters[c.metadata["source"]] = n + 1
        c.metadata["chunk_index"] = n
        c.metadata["chunk_id"] = hashlib.sha1(f"{c.metadata['source']}|{n}|{c.page_content}".encode()).hexdigest()[:20]
    return chunks
