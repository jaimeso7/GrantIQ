"""Optional, approved single-page public grant extraction. This is not a web crawler.

Each configured URL represents exactly one opportunity. Staff review the extracted
record and the funder's terms. No links, login, browser automation, or redirects
are followed. Missing eligibility, amounts, and geography remain unconfirmed.
"""
from datetime import date, datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import httpx
import soupsieve
import yaml

from ..schemas.domain import GrantRecord
from ..services.deduplication import canonical_url, normalized_text
from .base import HttpSource, SourceError, USER_AGENT, plain_text
from .grants_gov import parse_amount, parse_date, public_link

_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?"
          r"|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
# A day number is required so prose like "March 2024 report" is never read as a date.
_DATE = rf"{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\s*,?\s*\d{{4}})?"
_SEP = r"\s*(?:–|—|‒|-|to|through|until)\s*"
RANGE_RE = re.compile(rf"(?P<start>{_DATE}){_SEP}(?P<end>{_DATE})", re.I)
SINGLE_RE = re.compile(_DATE, re.I)
PIECE_RE = re.compile(rf"\s*({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?", re.I)
ROLLING = re.compile(r"\b(rolling basis|rolling|ongoing|year[- ]round|any time|no deadline)\b", re.I)
MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")
COUNTY_RE = re.compile(r"\b([A-Z][A-Za-z.\-']{2,24})\s+Count(?:y|ies)\b")
ELIGIBILITY_CUES = re.compile(r"\b(eligib\w*|budgets? of|must be|open to|limited to|only|"
                              r"organizations with|applicants?)\b", re.I)
_MONTH_NUMBERS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _sentence_around(text: str, start: int, end: int) -> str:
    """The whole sentence containing a match, kept verbatim for deadline_text."""
    left = max(text.rfind(mark, 0, start) for mark in (". ", "! ", "? "))
    right = min((pos for pos in (text.find(mark, end) for mark in (". ", "! ", "? ")) if pos >= 0),
                default=-1)
    return text[(0 if left < 0 else left + 2):(len(text) if right < 0 else right + 1)].strip()


def _piece(text: str) -> tuple[int, int, int | None] | None:
    match = PIECE_RE.match(text)
    if not match:
        return None
    return _MONTH_NUMBERS[match.group(1).lower()[:3]], int(match.group(2)), \
        int(match.group(3)) if match.group(3) else None


def parse_date_window(text: str) -> tuple[date | None, date | None, str]:
    """Read an application window from prose. Returns (start, end, verbatim sentence).

    Listing pages write ranges like "Application is open January 5 - March 3, 2027",
    where only the closing date carries a year. A missing year is inferred from the
    other end of the range, never from the current date: a fabricated deadline either
    hides a live grant or advertises a dead one.
    """
    match = RANGE_RE.search(text)
    if match:
        prose = _sentence_around(text, match.start(), match.end())
        start, end = _piece(match.group("start")), _piece(match.group("end"))
        if not start or not end:
            return None, None, prose
        (start_month, start_day, start_year), (end_month, end_day, end_year) = start, end
        if start_year is None and end_year is None:
            return None, None, prose
        if end_year is None:
            end_year = start_year
        if start_year is None:
            start_year = end_year
            # A window that would run backwards actually crosses New Year.
            if (start_month, start_day) > (end_month, end_day):
                start_year = end_year - 1
        try:
            opens, closes = date(start_year, start_month, start_day), date(end_year, end_month, end_day)
        except ValueError:
            return None, None, prose
        return (opens, closes, prose) if opens <= closes else (None, closes, prose)
    match = SINGLE_RE.search(text)
    if match:
        prose = _sentence_around(text, match.start(), match.end())
        piece = _piece(match.group(0))
        if piece and piece[2]:
            try:
                return None, date(piece[2], piece[0], piece[1]), prose
            except ValueError:
                return None, None, prose
        return None, None, prose
    return None, None, ""


def window_status(opens: date | None, closes: date | None, today: date) -> str:
    """Map an application window onto the GrantRecord status vocabulary."""
    if opens is None and closes is None:
        return "unknown"
    if closes is not None and today > closes:
        return "closed"
    if opens is not None and today < opens:
        return "forecasted"
    return "posted"


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

    def _guarded_get(self, url: str | None = None) -> dict:
        """Terms gate, fail-closed robots check, crawl-delay adoption, and challenge scan.

        Raises before any network request when terms are unreviewed. Shared by every
        approved-page adapter so the gate exists in exactly one place.
        """
        url = url or self.url
        if not self.terms_reviewed:
            raise SourceError("Source disabled: an administrator must review terms and set terms_reviewed: true")
        parts = urlsplit(url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        robots = self._cached_get(robots_url)
        # An HTML block page is not evidence of robots permission.
        if "user-agent:" not in robots["text"].lower():
            raise SourceError("robots.txt is missing valid directives; retrieval is blocked pending review")
        policy = RobotFileParser(robots_url)
        policy.parse(robots["text"].splitlines())
        if not policy.can_fetch(USER_AGENT, url):
            raise SourceError("robots.txt disallows this opportunity URL")
        delay = policy.crawl_delay(USER_AGENT) or policy.crawl_delay("*")
        if delay:
            self.min_interval = max(self.min_interval, float(delay))
        rate = policy.request_rate(USER_AGENT) or policy.request_rate("*")
        if rate and rate.requests:
            self.min_interval = max(self.min_interval, rate.seconds / rate.requests)
        entry = self._cached_get(url)
        lower_text = entry["text"].lower()
        if any(marker in lower_text for marker in ("g-recaptcha", "h-captcha", "cf-chl-", 'type="password"', "type='password'")):
            raise SourceError("Page presents a login or access challenge; manual review is required")
        return entry

    def fetch_grants(self):
        self.errors.clear()
        try:
            record = self.normalize_grant(self._guarded_get())
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


class ListingPageSource(GenericPageSource):
    """One approved page that advertises several opportunities, one row each.

    Still not a crawler: exactly two requests are made, robots.txt and the listing
    page itself. Each row's "more information" link is recorded as application_url
    for staff to follow; it is never retrieved. Amounts, populations and applicant
    types are not on a listing page and are left unknown rather than guessed.
    """

    DEFAULT_SELECTORS = {"row": "details.e-n-accordion-item",
                         "title": "h6.e-n-accordion-item-title-text",
                         "application_url": "a[href]"}
    MAX_DESCRIPTION = 4000
    MAX_RAW_TEXT = 8000

    def __init__(self, name: str, url: str, *, selectors: dict[str, str] | None = None,
                 defaults: dict | None = None, max_rows: int = 100, today: date | None = None,
                 allow_detail_fetch: bool = False, **kwargs):
        super().__init__(name=name, url=url, selectors={**self.DEFAULT_SELECTORS, **(selectors or {})}, **kwargs)
        self.defaults = defaults or {}
        self.max_rows = max(1, int(max_rows))
        self.today = today
        self.allow_detail_fetch = allow_detail_fetch is True
        self._row_keys: dict[str, int] = {}
        for key, selector in self.selectors.items():
            try:
                soupsieve.compile(selector)
            except Exception as exc:  # soupsieve raises several exception types
                raise SourceError(f"Invalid {key!r} selector {selector!r}: {exc}") from exc

    def _row_source_id(self, detail_href: str | None, title: str) -> tuple[str, bool]:
        """Identity per row. Without this every row collapses into a single grant.

        The detail-page permalink is preferred because it survives row reordering,
        title edits and the annual cycle; the normalized title is the fallback for a
        row with no link. The listing:v1 namespace makes any future change to this
        derivation an explicit, reviewable bump rather than silent mass duplication.
        """
        key = canonical_url(urljoin(self.url, detail_href)) if detail_href else f"title:{normalized_text(title)}"
        count = self._row_keys.get(key, 0) + 1
        self._row_keys[key] = count
        unique = key if count == 1 else f"{key}#{count}"
        return hashlib.sha256(f"listing:v1|{self.url}|{unique}".encode()).hexdigest(), count > 1

    def fetch_grants(self):
        self.errors.clear()
        self._row_keys = {}
        try:
            if self.allow_detail_fetch:
                raise SourceError("Detail-page retrieval is configured but not implemented; "
                                  "this adapter reads the listing page only.")
            entry = self._guarded_get()
            soup = BeautifulSoup(entry["text"], "html.parser")
            for node in soup(["script", "style", "noscript", "iframe", "nav", "footer", "header", "form"]):
                node.decompose()
            rows = soup.select(self.selectors["row"])
        except (SourceError, ValueError, OSError, TypeError) as exc:
            self.stats["rejected"] += 1
            self._error(str(exc))
            return
        self.stats["rows_matched"] = len(rows)
        # Loud on structural breakage: a silent empty result would let the dashboard
        # report a clean run while staff conclude there are no local grants.
        if not rows:
            self.stats["rejected"] += 1
            self._error(f"Listing selector {self.selectors['row']!r} matched no rows on {self.url}; "
                        "the page layout likely changed and no opportunities were ingested.")
            return
        if len(rows) > self.max_rows:
            self.stats["rejected"] += 1
            self._error(f"Listing selector {self.selectors['row']!r} matched {len(rows)} rows, above the "
                        f"{self.max_rows}-row cap; the selector is too broad and no opportunities were ingested.")
            return
        for index, row in enumerate(rows, 1):
            self.stats["found"] += 1
            try:
                record = self.normalize_grant({"row": row, "retrieved_at": entry.get("retrieved_at")})
            except (SourceError, ValueError, OSError, TypeError) as exc:
                self.stats["rejected"] += 1
                self._error(f"row {index}: {type(exc).__name__}: {exc}")
                continue
            self.stats["normalized"] += 1
            yield record

    def normalize_grant(self, raw_data: dict) -> GrantRecord:
        row = raw_data["row"]
        title_node = row.select_one(self.selectors["title"])
        title = plain_text(title_node.get_text(" ", strip=True)) if title_node else ""
        if not title:
            raise SourceError(f"Row matched {self.selectors['row']!r} but has no title")
        row_text = plain_text(row.get_text(" ", strip=True))
        description = row_text[len(title):].strip() if row_text.startswith(title) else row_text

        warnings = ["Listing-page extraction requires human review; eligibility, amounts, and open "
                    "status are unconfirmed.",
                    "The linked detail page was not retrieved; this record reflects only the listing summary."]
        link = row.select_one(self.selectors["application_url"]) if self.selectors.get("application_url") else None
        href = link.get("href") if link and link.get("href") else None
        source_id, collided = self._row_source_id(href, title)
        if collided:
            warnings.append("Another row on this page resolved to the same identity; review both records.")

        opens, closes, prose = parse_date_window(row_text)
        if opens is None and closes is None:
            rolling = ROLLING.search(row_text)
            if rolling:
                # deadline_text carries the verbatim phrase so the existing rolling
                # rule in scoring._readiness awards credit without a fabricated date.
                prose, status = _sentence_around(row_text, rolling.start(), rolling.end()), "posted"
            else:
                status = "unknown"
                warnings.append("No application window could be read from the listing; "
                                "confirm the current cycle with the funder.")
        else:
            status = window_status(opens, closes, self.today or date.today())

        restrictions = [f"{name} County" for name in dict.fromkeys(COUNTY_RE.findall(row_text))]
        scope = "local" if restrictions else "unknown"
        if not restrictions and self.defaults.get("geographic_restrictions"):
            restrictions = list(self.defaults["geographic_restrictions"])
            scope = self.defaults.get("geography_scope", "unknown")
            warnings.append("Geographic eligibility was asserted by an administrator in configuration, "
                            "not read from the source page.")
        amounts = list(dict.fromkeys(MONEY_RE.findall(row_text)))
        if amounts:
            warnings.append(f"The listing mentions {', '.join(amounts)} without saying whether this is an "
                            "award size, a total pool, or a cap on the applicant's own budget; amounts were "
                            "left unset for staff to classify.")
        eligibility = " ".join(part.strip() for part in re.split(r"(?<=[.!?])\s+", row_text)
                               if ELIGIBILITY_CUES.search(part))

        return GrantRecord(
            source=getattr(self, "source_key", self.name), source_id=source_id,
            source_url=self.url, application_url=public_link(urljoin(self.url, href)) if href else None,
            funder_name=self.name, grant_title=title, description=description[:self.MAX_DESCRIPTION],
            eligibility_text=eligibility[:2000],
            geographic_restrictions=restrictions,
            geography_scope=scope if scope in {"local", "state", "regional", "national"} else "unknown",
            open_date=opens, deadline=closes, deadline_text=prose, grant_status=status,
            last_checked=datetime.fromtimestamp(raw_data.get("retrieved_at") or time.time(), timezone.utc),
            # Per row, never the whole page: verification.source_revision hashes this,
            # so a page-wide value would invalidate every row's review when one changes.
            raw_text=row_text[:self.MAX_RAW_TEXT], warnings=warnings)


class ListingScraperSource(ListingPageSource):
    """Configuration-dict entry point for listing pages, mirroring GenericScraperSource."""

    def __init__(self, item: dict, **kwargs):
        kwargs.setdefault("cache_dir", os.getenv("GRANTIQ_CACHE_DIR", "data/cache"))
        if item.get("max_response_bytes"):
            kwargs.setdefault("max_response_bytes", int(item["max_response_bytes"]))
        if item.get("source_key"):
            self.source_key = item["source_key"]
        super().__init__(name=item["name"], url=item["url"],
                         terms_reviewed=item.get("terms_reviewed", False),
                         selectors=item.get("selectors"), defaults=item.get("defaults"),
                         max_rows=item.get("max_rows", 100),
                         allow_detail_fetch=item.get("allow_detail_fetch", False), **kwargs)
