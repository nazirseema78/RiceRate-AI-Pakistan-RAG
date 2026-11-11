"""SQLite access helpers. All queries use parameter binding (never string formatting of user input)."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from backend.config import get_settings

_SCHEMA = Path(__file__).with_name("schema.sql")
_init_lock = threading.Lock()
_initialized: set[str] = set()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path: Path | None = None) -> None:
    path = Path(path or get_settings().database_path)
    with _init_lock:
        conn = _connect(path)
        try:
            conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()
        _initialized.add(str(path))


@contextmanager
def get_conn(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(path or get_settings().database_path)
    if str(path) not in _initialized:
        init_db(path)
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_or_create(conn: sqlite3.Connection, table: str, unique: dict[str, Any], extra: dict[str, Any] | None = None) -> int:
    """Return the id of a row matching `unique`, inserting it if missing. Table/column names are internal constants."""
    assert table in {"products", "markets", "price_sources"}
    where = " AND ".join(f"{k} = ?" for k in unique)
    found = conn.execute(f"SELECT id FROM {table} WHERE {where}", tuple(unique.values())).fetchone()
    if found:
        return int(found["id"])
    data = {**unique, **(extra or {})}
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))
    return int(cur.lastrowid)
