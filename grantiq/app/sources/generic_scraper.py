"""Optional, approved single-page public grant extraction. This is not a web crawler.

Each configured URL represents exactly one opportunity. Staff review the extracted
record and the funder's terms. No links, login, browser automation, or redirects
are followed. Missing eligibility, amounts, and geography remain unconfirmed.
"""
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import httpx
import yaml

from ..schemas.domain import GrantRecord
from .base import HttpSource, SourceError, USER_AGENT, plain_text
from .grants_gov import parse_amount, parse_date, public_link


def validate_public_url(url: str, resolver=socket.getaddrinfo) -> tuple[str, list[str]]:
    """Require HTTPS on its standard port and reject all nonpublic DNS addresses."""
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.port not in (None, 443) or "\\" in url or any(ord(c) < 32 for c in url)):
            raise ValueError("Only public HTTPS URLs without credentials on port 443 are allowed")
        hostname = parts.hostname.rstrip(".").encode("idna").decode("ascii")
        addresses = list(dict.fromkeys(result[4][0] for result in resolver(hostname, 443, type=socket.SOCK_STREAM)))
        if not addresses:
            raise ValueError("Host has no DNS addresses")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global or ip.is_multicast or ip.is_reserved:
                raise ValueError("Nonpublic, local, or reserved destinations are forbidden")
        return hostname, addresses
    except (ValueError, OSError, UnicodeError) as exc:
        raise SourceError(f"Approved source URL failed public-address validation: {exc}") from exc


class PublicOnlyTransport(httpx.BaseTransport):
    """Pin each request to a validated public IP, retaining TLS hostname checks.

    Prevents a second DNS resolution from rebinding an approved host to a private
    IP between validation and connection. The documented httpcore sni_hostname
    extension preserves certificate verification for the original hostname.
    """

    def __init__(self, *, resolver=socket.getaddrinfo, transport=None):
        self.resolver = resolver
        # Separate TLS connections prevent pooling two approved hostnames that
        # resolve to the same IP before checking each hostname's certificate.
        self.transport = transport or httpx.HTTPTransport(retries=0,
            limits=httpx.Limits(max_keepalive_connections=0))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        hostname, addresses = validate_public_url(str(request.url), resolver=self.resolver)
        headers = request.headers.copy()
        headers["Host"] = hostname
        pinned = httpx.Request(request.method, request.url.copy_with(host=addresses[0]),
            headers=headers, stream=request.stream,
            extensions={**request.extensions, "sni_hostname": hostname})
        return self.transport.handle_request(pinned)

    def close(self):
        self.transport.close()


class GenericPageSource(HttpSource):
    """One approved page with optional CSS selectors maintained by administrators.

    selectors supports title, description, eligibility, deadline, award_min,
    award_max, application_url. The deadline selector may expose datetime/content;
    the application_url selector must select an anchor with an href.
    """

    def __init__(self, name: str, url: str, *, terms_reviewed: bool = False,
                 selectors: dict[str, str] | None = None, cache_dir: str | Path | None = None,
                 cache_seconds: int = 21600, client: httpx.Client | None = None,
                 resolver=socket.getaddrinfo, **kwargs):
        self.name = name
        self.url = urlunsplit((*urlsplit(url)[:4], ""))
        self.terms_reviewed = terms_reviewed is True
        self.selectors = selectors or {}
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_seconds = max(0, cache_seconds)
        self.resolver = resolver
        created_client = client is None
        if client is None:
            client = httpx.Client(transport=PublicOnlyTransport(resolver=resolver), timeout=30,
                                  trust_env=False, follow_redirects=False)
        kwargs.setdefault("min_interval", 1)
        kwargs.setdefault("max_response_bytes", 2_000_000)
        super().__init__(client=client, **kwargs)
        self._owns_client = created_client

    def _cached_get(self, url: str) -> dict:
        validate_public_url(url, resolver=self.resolver)
        cache_file = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json") if self.cache_dir else None
        if cache_file and cache_file.exists():
            try:
                entry = json.loads(cache_file.read_text(encoding="utf-8"))
                if (entry.get("url") == url and 0 <= time.time() - entry["retrieved_at"] < self.cache_seconds
                        and len(entry["text"].encode()) <= self.max_response_bytes):
                    return entry
            except (OSError, ValueError, KeyError, TypeError):
                pass
        response = self._request("GET", url)
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and not any(allowed in content_type for allowed in ("text/", "application/xhtml+xml")):
            raise SourceError("Only public text/HTML documents are supported")
        entry = {"url": url, "retrieved_at": time.time(), "text": response.text}
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(entry), encoding="utf-8")
        return entry

    def fetch_grants(self):
        self.errors.clear()
        try:
            if not self.terms_reviewed:
                raise SourceError("Source disabled: an administrator must review terms and set terms_reviewed: true")
            parts = urlsplit(self.url)
            robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            robots = self._cached_get(robots_url)
            # An HTML block page is not evidence of robots permission.
            if "user-agent:" not in robots["text"].lower():
                raise SourceError("robots.txt is missing valid directives; retrieval is blocked pending review")
            policy = RobotFileParser(robots_url)
            policy.parse(robots["text"].splitlines())
            if not policy.can_fetch(USER_AGENT, self.url):
                raise SourceError("robots.txt disallows this opportunity URL")
            delay = policy.crawl_delay(USER_AGENT) or policy.crawl_delay("*")
            if delay:
                self.min_interval = max(self.min_interval, float(delay))
            rate = policy.request_rate(USER_AGENT) or policy.request_rate("*")
            if rate and rate.requests:
                self.min_interval = max(self.min_interval, rate.seconds / rate.requests)
            entry = self._cached_get(self.url)
            lower_text = entry["text"].lower()
            if any(marker in lower_text for marker in ("g-recaptcha", "h-captcha", "cf-chl-", 'type="password"', "type='password'")):
                raise SourceError("Page presents a login or access challenge; manual review is required")
            record = self.normalize_grant(entry)
            self.stats["found"] += 1
            self.stats["normalized"] += 1
            yield record
        except (SourceError, ValueError, OSError, TypeError) as exc:
            self.stats["rejected"] += 1
            self._error(str(exc))

    def normalize_grant(self, raw_data: dict) -> GrantRecord:
        soup = BeautifulSoup(raw_data["text"], "html.parser")
        for node in soup(["script", "style", "noscript", "iframe", "nav", "footer", "header", "form"]):
            node.decompose()

        def select(key, fallback=None):
            selector = self.selectors.get(key, fallback)
            return soup.select_one(selector) if selector else None

        def value(key, fallback=None):
            node = select(key, fallback)
            return plain_text(node.get("datetime") or node.get("content") or node.get_text(" ", strip=True)) if node else ""

        def values(key):
            selector = self.selectors.get(key)
            return list(dict.fromkeys(plain_text(node.get_text(" ", strip=True)) for node in soup.select(selector) if node.get_text(strip=True))) if selector else []

        title = value("title", "h1") or value("title", "title")
        description = value("description", "main") or value("description", "article") or plain_text(str(soup))
        if not title or len(description) < 40:
            raise SourceError("The page does not contain an identifiable grant title and description")
        link = select("application_url")
        application_url = public_link(urljoin(self.url, link.get("href", ""))) if link and link.get("href") else None
        deadline_text = value("deadline")
        scope = value("geography_scope").lower()
        status = value("grant_status").lower()
        return GrantRecord(source=getattr(self, "source_key", self.name), source_id=hashlib.sha256(self.url.encode()).hexdigest(),
            source_url=self.url, application_url=application_url, funder_name=self.name,
            grant_title=title, description=description, eligibility_text=value("eligibility"),
            applicant_types=values("applicant_types"), geographic_restrictions=values("geography"),
            populations_served=values("populations"), categories=values("categories"), program_areas=values("programs"),
            geography_scope=scope if scope in {"local", "state", "regional", "national"} else "unknown",
            grant_status=status if status in {"posted", "forecasted", "closed", "archived"} else "unknown",
            award_min=parse_amount(value("award_min")), award_max=parse_amount(value("award_max")),
            deadline=parse_date(deadline_text), deadline_text=deadline_text,
            last_checked=datetime.fromtimestamp(raw_data.get("retrieved_at", time.time()), timezone.utc),
            raw_text=plain_text(str(soup)), warnings=[
                "Approved-page extraction requires human review; eligibility, geography, and open status are unconfirmed.",
                "A source page may list several programs; configure a separate opportunity page and selectors for each grant."])


def load_approved_sources(path: str | Path, *, cache_dir: str | Path | None = None) -> list[GenericPageSource]:
    """Read only the administrator-controlled file; ordinary users cannot add URLs."""
    path = Path(path)
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = payload if isinstance(payload, list) else payload.get("sources", [])
    sources = []
    for entry in entries:
        if entry.get("enabled") is not True:
            continue
        if entry.get("parser", "generic") != "generic":
            raise ValueError(f"Unsupported source parser: {entry.get('parser')}")
        sources.append(GenericPageSource(name=entry["name"], url=entry["url"],
            terms_reviewed=entry.get("terms_reviewed", False), selectors=entry.get("selectors"), cache_dir=cache_dir))
    return sources


class GenericScraperSource(GenericPageSource):
    """Configuration-dict entry point consumed by the ingestion coordinator."""

    def __init__(self, item: dict, **kwargs):
        kwargs.setdefault("cache_dir", os.getenv("GRANTIQ_CACHE_DIR", "data/cache"))
        if item.get("source_key"):
            self.source_key = item["source_key"]
        super().__init__(name=item["name"], url=item["url"],
                         terms_reviewed=item.get("terms_reviewed", False),
                         selectors=item.get("selectors"), **kwargs)
