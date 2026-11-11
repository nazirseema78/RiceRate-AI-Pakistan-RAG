"""HTTP client for the FastAPI backend. The frontend never touches SQLite or ChromaDB directly."""
from __future__ import annotations

import os

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


class BackendError(RuntimeError):
    pass


def _clean(params: dict | None) -> dict:
    return {k: v for k, v in (params or {}).items() if v not in (None, "", "All")}


def get(path: str, params: dict | None = None, timeout: float = 30) -> dict:
    try:
        r = requests.get(f"{BACKEND_URL}{path}", params=_clean(params), timeout=timeout)
    except requests.RequestException as e:
        raise BackendError(f"Cannot reach backend at {BACKEND_URL}. Is FastAPI running? ({e.__class__.__name__})") from e
    if not r.ok:
        raise BackendError(f"Backend error {r.status_code}: {r.text[:300]}")
    return r.json()


def request(method: str, path: str, payload: dict | None = None, headers: dict | None = None, timeout: float = 180) -> dict:
    try:
        r = requests.request(method, f"{BACKEND_URL}{path}", json=payload, headers=headers or {}, timeout=timeout)
    except requests.RequestException as e:
        raise BackendError(f"Cannot reach backend at {BACKEND_URL}. Is FastAPI running? ({e.__class__.__name__})") from e
    if not r.ok:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:300]
        raise BackendError(f"Backend error {r.status_code}: {detail}")
    return r.json()


def post(path: str, payload: dict, headers: dict | None = None, timeout: float = 180) -> dict:
    return request("POST", path, payload, headers, timeout)


@st.cache_data(ttl=60, show_spinner=False)
def cached_get(path: str, params: tuple = ()) -> dict:
    return get(path, dict(params))


def safe_get(path: str, params: dict | None = None) -> dict | None:
    """GET with a friendly error box instead of a stack trace."""
    try:
        return cached_get(path, tuple(sorted(_clean(params).items())))
    except BackendError as e:
        st.error(str(e))
        return None
