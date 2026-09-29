"""Shared source contract, text cleanup, bounded HTTP retries and request logging."""
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime, timezone
import logging
import time
import html
from typing import Any

from bs4 import BeautifulSoup
import httpx

from ..schemas.domain import GrantRecord

logger = logging.getLogger(__name__)
USER_AGENT = "GrantIQ/1.0 (nonprofit public grant research; respectful, bounded retrieval)"


class SourceError(RuntimeError):
    """A failed source request or invalid upstream response."""


def plain_text(value: Any) -> str:
    if value is None:
        return ""
    if "<" not in str(value):
        return " ".join(html.unescape(str(value)).split())
    soup = BeautifulSoup(str(value), "html.parser")
    for node in soup(["script", "style", "noscript", "iframe"]):
        node.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


class GrantSource(ABC):
    name: str

    @abstractmethod
    def fetch_grants(self) -> Iterable[GrantRecord]:
        """Retrieve normalized records; report source failures in errors."""

    @abstractmethod
    def normalize_grant(self, raw_data: dict) -> GrantRecord:
        """Normalize evidence without inventing missing fields."""


class HttpSource(GrantSource):
    """Synchronous client suitable for the background ingestion worker and CLI.

    Inject a MockTransport-backed client and sleep function for deterministic tests.
    The source owns only clients it creates itself.
    """

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 30,
                 min_interval: float = 0.5, retries: int = 2, sleep=time.sleep,
                 max_response_bytes: int = 5_000_000):
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False,
                                             trust_env=False, headers={"User-Agent": USER_AGENT})
        self.min_interval = max(0, min_interval)
        self.retries = min(max(0, retries), 5)
        self.sleep = sleep
        self.max_response_bytes = max_response_bytes
        self._last_request = 0.0
        self.errors: list[str] = []
        self.stats = {"http_requests": 0, "http_retries": 0, "http_failures": 0,
                      "found": 0, "normalized": 0, "rejected": 0, "truncated": False}

    def close(self):
        if self._owns_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _error(self, message: str):
        self.errors.append(message)
        logger.warning("source=%s error=%s", self.name, message)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_error = "Unknown request failure"
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                self.sleep(wait)
            self._last_request = time.monotonic()
            self.stats["http_requests"] += 1
            retry_after = 0.0
            try:
                with self.client.stream(method, url, follow_redirects=False,
                                        headers={"User-Agent": USER_AGENT}, **kwargs) as stream:
                    chunks = []
                    size = 0
                    for chunk in stream.iter_bytes(chunk_size=65536):
                        size += len(chunk)
                        if size > self.max_response_bytes:
                            self.stats["http_failures"] += 1
                            raise SourceError(f"Response exceeds the configured size limit: {url}")
                        chunks.append(chunk)
                    headers = {k: v for k, v in stream.headers.items()
                               if k.lower() not in {"content-encoding", "content-length"}}
                    response = httpx.Response(stream.status_code, headers=headers,
                                              content=b"".join(chunks), request=stream.request)
                logger.info("source=%s retrieved_at=%s status=%s url=%s", self.name,
                            datetime.now(timezone.utc).isoformat(), response.status_code, url)
                if 200 <= response.status_code < 300:
                    return response
                # Redirects are never followed implicitly, including on approved pages.
                last_error = f"HTTP {response.status_code} from {url}"
                if response.status_code not in {408, 429, 500, 502, 503, 504}:
                    self.stats["http_failures"] += 1
                    raise SourceError(last_error)
                try:
                    retry_after = min(30.0, max(0, float(response.headers.get("Retry-After", 0))))
                except ValueError:
                    pass
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__} fetching {url}: {exc}"
                logger.warning("source=%s attempt=%d error=%s", self.name, attempt + 1, last_error)
            if attempt < self.retries:
                self.stats["http_retries"] += 1
                self.sleep(max(2 ** attempt, retry_after))
        self.stats["http_failures"] += 1
        raise SourceError(last_error)
