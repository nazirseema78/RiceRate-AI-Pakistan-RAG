-- RiceRate AI Pakistan - SQLite schema
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    product_type TEXT NOT NULL CHECK (product_type IN ('paddy', 'rice', 'broken_rice')),
    variety TEXT NOT NULL,
    grade TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    province TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL,
    region TEXT NOT NULL DEFAULT '',
    UNIQUE (name, city, country)
);

CREATE TABLE IF NOT EXISTS price_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    data_nature TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    requires_api_key INTEGER NOT NULL DEFAULT 0,
    last_attempted_at TEXT,
    last_success_at TEXT,
    last_observation_at TEXT,
    availability_status TEXT NOT NULL DEFAULT 'unknown',
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS market_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    market_id INTEGER NOT NULL REFERENCES markets(id),
    source_id INTEGER NOT NULL REFERENCES price_sources(id),
    price REAL NOT NULL CHECK (price > 0),
    currency TEXT NOT NULL,
    original_unit TEXT NOT NULL,
    normalized_price REAL NOT NULL,
    normalized_unit TEXT NOT NULL,
    price_category TEXT NOT NULL CHECK (price_category IN ('wholesale', 'retail', 'export', 'broker_quotation')),
    observed_at TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    source_document TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL,
    data_nature TEXT NOT NULL CHECK (data_nature IN ('synthetic', 'live', 'historical', 'imported')),
    is_synthetic INTEGER NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    dedup_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_prices_lookup ON market_prices (product_id, market_id, price_category, observed_at);

-- one end-of-day record per product/market/category/source/day (rolled up from market_prices)
CREATE TABLE IF NOT EXISTS historical_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    market_id INTEGER NOT NULL REFERENCES markets(id),
    source_id INTEGER NOT NULL REFERENCES price_sources(id),
    price_category TEXT NOT NULL,
    price_date TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    original_unit TEXT NOT NULL,
    normalized_price REAL NOT NULL,
    normalized_unit TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL,
    UNIQUE (product_id, market_id, source_id, price_category, price_date)
);

CREATE TABLE IF NOT EXISTS broker_quotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_ref TEXT NOT NULL UNIQUE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    market_id INTEGER NOT NULL REFERENCES markets(id),
    buyer TEXT NOT NULL,
    price REAL NOT NULL CHECK (price > 0),
    currency TEXT NOT NULL,
    unit TEXT NOT NULL,
    normalized_price REAL NOT NULL,
    normalized_unit TEXT NOT NULL,
    quantity_mt REAL,
    delivery_terms TEXT NOT NULL DEFAULT '',
    quoted_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_document TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_ref TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    region TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('news', 'commentary', 'report', 'price_observation')),
    published_at TEXT NOT NULL,
    source_name TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    source_document TEXT NOT NULL DEFAULT '',
    is_synthetic INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_key TEXT NOT NULL,
    trigger TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    fetched INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS source_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    doc_type TEXT NOT NULL,
    publication_date TEXT,
    sha256 TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    is_synthetic INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
