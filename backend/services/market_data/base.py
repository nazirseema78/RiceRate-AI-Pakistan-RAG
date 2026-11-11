"""Provider interface shared by free, synthetic, CSV and (future) paid market data connectors."""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import requests

from backend.config import get_settings
from backend.models.price import PriceObservation, SourceMetadata

log = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    observations: list[PriceObservation] = field(default_factory=list)
    quotations: list[dict] = field(default_factory=list)   # broker quotations (normalised dicts)
    news: list[dict] = field(default_factory=list)
    message: str = ""


@dataclass
class Availability:
    available: bool
    status: str  # available | disabled | unavailable | not_configured
    detail: str = ""


class ProviderError(RuntimeError):
    pass


class MarketDataProvider(ABC):
    """Abstract interface every connector implements. Credentials stay on the backend only."""

    provider_key: str = "base"

    @abstractmethod
    def get_source_metadata(self) -> SourceMetadata: ...

    @abstractmethod
    def check_availability(self) -> Availability: ...

    @abstractmethod
    def fetch_latest_prices(self) -> ProviderResult: ...

    def fetch_historical_prices(self, start: date | None = None, end: date | None = None) -> ProviderResult:
        """Default: providers without a history feed return nothing (never fabricated data)."""
        return ProviderResult(message="historical fetch not supported by this provider")


class RateLimiter:
    """Minimum interval between calls (per provider instance)."""

    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self.min_interval_s:
                time.sleep(self.min_interval_s - delta)
            self._last = time.monotonic()


def http_get(url: str, *, params: dict | None = None, headers: dict | None = None,
             limiter: RateLimiter | None = None, session: requests.Session | None = None) -> requests.Response:
    """GET with timeout, bounded retries (5xx / network errors only) and polite User-Agent."""
    s = get_settings()
    hdrs = {"User-Agent": s.http_user_agent, **(headers or {})}
    sess = session or requests
    last_exc: Exception | None = None
    for attempt in range(s.http_max_retries + 1):
        if limiter:
            limiter.wait()
        try:
            resp = sess.get(url, params=params, headers=hdrs, timeout=s.http_timeout_seconds)
            if resp.status_code >= 500:
                raise ProviderError(f"HTTP {resp.status_code} from {url}")
            return resp
        except (requests.RequestException, ProviderError) as e:
            last_exc = e
            log.warning("GET %s failed (attempt %s): %s", url, attempt + 1, e)
            time.sleep(min(2 ** attempt, 8))
    raise ProviderError(f"GET {url} failed after retries: {last_exc}")
