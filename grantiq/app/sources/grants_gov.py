"""Official key-free Grants.gov API integration.

Reference: https://www.grants.gov/api/common/search2 and
https://www.grants.gov/api/common/fetchopportunity (verified September 2026).
Search records are hydrated with their full synopsis or forecast before scoring.
"""
from collections.abc import Iterable
from datetime import date, datetime, timezone
import logging
import math
import re
from typing import Any
from urllib.parse import urlsplit

from ..schemas.domain import GrantRecord
from .base import HttpSource, SourceError, plain_text

logger = logging.getLogger(__name__)
DEFAULT_KEYWORDS = ["vision", "blindness", "eye health", "healthcare", "preventive health",
                    "children", "youth", "education", "accessibility", "disability", "aging",
                    "community health", "health equity", "workforce development"]
API_BASE = "https://api.grants.gov/v1/api"


def first(*values):
    """Select a present value, retaining meaningful zero and false values."""
    return next((v for v in values if v is not None and v != ""), None)


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for candidate, fmt in [(text[:10], "%Y-%m-%d"), (text, "%m/%d/%Y"),
                            (text[:12], "%b %d, %Y"), (text, "%B %d, %Y")]:
        try:
            return datetime.strptime(candidate.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = float(str(value).replace(",", "").replace("$", "").strip())
        return amount if math.isfinite(amount) and amount >= 0 else None
    except (ValueError, TypeError):
        return None


def descriptions(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    values = [plain_text(first(item.get("description"), item.get("programTitle"), item.get("name")))
              if isinstance(item, dict) else plain_text(item) for item in items]
    return list(dict.fromkeys(value for value in values if value))


def public_link(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return value.strip()
    except ValueError:
        pass
    return None


class GrantsGovSource(HttpSource):
    name = "Grants.gov"

    def __init__(self, keywords: list[str] | None = None, max_records: int = 100,
                 page_size: int = 25, max_search_pages: int | None = None, **kwargs):
        super().__init__(**kwargs)
        self.keywords = list(dict.fromkeys(keywords if keywords is not None else DEFAULT_KEYWORDS))
        self.max_records = min(max(1, max_records), 10000)
        self.page_size = min(max(1, page_size), 100)
        self.max_search_pages = max_search_pages or min(1000, self.max_records * 2 + len(self.keywords))

    def _post(self, endpoint: str, payload: dict) -> dict:
        response = self._request("POST", f"{API_BASE}/{endpoint}", json=payload)
        try:
            body = response.json()
        except ValueError as exc:
            raise SourceError(f"{endpoint}: malformed JSON response") from exc
        if not isinstance(body, dict) or body.get("errorcode", 0) not in (0, "0"):
            raise SourceError(f"{endpoint}: Grants.gov reported an API error")
        if not isinstance(body.get("data"), dict):
            raise SourceError(f"{endpoint}: response is missing the data object")
        return body["data"]

    def fetch_grants(self) -> Iterable[GrantRecord]:
        self.errors.clear()
        seen: set[str] = set()
        # Round-robin keyword pages prevent a broad first query exhausting the cap
        # before more specific program interests are searched.
        searches = [{"keyword": keyword, "offset": 0} for keyword in self.keywords]
        page_count = 0
        prior_pages: set[tuple] = set()
        while searches and len(seen) < self.max_records:
            next_searches = []
            for search in searches:
                if len(seen) >= self.max_records:
                    next_searches.append(search)
                    continue
                if page_count >= self.max_search_pages:
                    self.stats["truncated"] = True
                    self._error(f"Search pagination reached the {self.max_search_pages}-page safety limit; coverage is incomplete.")
                    return
                rows = min(self.page_size, max(1, self.max_records // max(1, len(self.keywords))),
                           self.max_records - len(seen))
                try:
                    page_count += 1
                    data = self._post("search2", {"keyword": search["keyword"], "rows": rows,
                        "oppStatuses": "forecasted|posted", "startRecordNum": search["offset"], "sortBy": "openDate|desc"})
                    hits = data.get("oppHits")
                    if not isinstance(hits, list):
                        raise SourceError("search2: missing opportunity hit list")
                    self.stats["found"] += len(hits)
                    hit_count = int(data.get("hitCount", len(hits)))
                    fingerprint = (search["keyword"], *(str(hit.get("id")) for hit in hits if isinstance(hit, dict)))
                    if hits and fingerprint in prior_pages:
                        raise SourceError("search2 repeated a previously returned page; pagination was stopped")
                    prior_pages.add(fingerprint)
                except (SourceError, TypeError, ValueError) as exc:
                    self._error(f"Search '{search['keyword']}' failed: {exc}")
                    continue
                if hits and search["offset"] + len(hits) < hit_count:
                    next_searches.append({"keyword": search["keyword"], "offset": search["offset"] + len(hits)})
                for hit in hits:
                    if not isinstance(hit, dict) or not str(hit.get("id", "")).isdigit():
                        self.stats["rejected"] += 1
                        self._error("Skipped a malformed Grants.gov search record without a numeric ID.")
                        continue
                    source_id = str(hit["id"])
                    if source_id in seen:
                        continue
                    if len(seen) >= self.max_records:
                        self.stats["truncated"] = True
                        break
                    seen.add(source_id)
                    try:
                        detail = self._post("fetchOpportunity", {"opportunityId": int(source_id)})
                        if str(detail.get("id", "")) != source_id:
                            raise SourceError("fetchOpportunity returned a different or missing opportunity ID")
                        record = self.normalize_grant({**detail, "_search": hit})
                    except (SourceError, ValueError, TypeError) as exc:
                        # Do not replace a previously rich record with partial metadata.
                        self.stats["rejected"] += 1
                        self._error(f"Opportunity {source_id} detail/normalization failed: {exc}")
                        continue
                    self.stats["normalized"] += 1
                    yield record
            searches = next_searches
        if searches or self.stats["truncated"]:
            self.stats["truncated"] = True
            self._error(f"Refresh reached the {self.max_records}-opportunity limit; results are a bounded subset. "
                        "Narrow configured keywords or raise GRANTIQ_MAX_RECORDS to extend coverage.")
        logger.info("source=%s stats=%s", self.name, self.stats)

    def normalize_grant(self, raw_data: dict) -> GrantRecord:
        raw = raw_data.get("data", raw_data)
        search = raw.get("_search", {})
        synopsis = raw.get("synopsis") or raw.get("forecast") or {}
        warnings = []
        source_id = str(first(raw.get("id"), search.get("id"), raw.get("opportunityId")) or "")
        if not source_id.isdigit():
            raise ValueError("Grants.gov opportunity requires a numeric ID")
        title = plain_text(first(raw.get("opportunityTitle"), raw.get("title"), search.get("title")))
        if not title:
            raise ValueError("Grants.gov opportunity is missing its title")
        description = plain_text(first(synopsis.get("synopsisDesc"), synopsis.get("forecastDesc"),
                                       raw.get("description")))
        applicant_types = descriptions(synopsis.get("applicantTypes"))
        extra_eligibility = plain_text(first(synopsis.get("applicantEligibilityDesc"),
                                             synopsis.get("additionalInformationOnEligibility")))
        eligibility_text = "; ".join(applicant_types + ([extra_eligibility] if extra_eligibility else []))
        if not applicant_types:
            warnings.append("Applicant types are unconfirmed; review the official eligibility requirements.")
        warnings.append("Geographic eligibility is unconfirmed; review the full announcement.")
        if not description:
            warnings.append("The official record has no opportunity description.")
        status = str(first(search.get("oppStatus"), raw.get("oppStatus"), raw.get("ost")) or "").lower()
        if status not in {"posted", "forecasted", "closed", "archived"}:
            status = "forecasted" if raw.get("forecast") and not raw.get("synopsis") else "unknown"
        deadline_value = first(synopsis.get("responseDateStr"), synopsis.get("responseDate"),
                               synopsis.get("closeDate"), search.get("closeDate"), raw.get("closeDate"))
        deadline_text = plain_text(first(synopsis.get("responseDateDesc"), raw.get("originalDueDateDesc")))
        if status == "forecasted":
            deadline_value = first(synopsis.get("estApplicationResponseDateStr"),
                                   synopsis.get("estApplicationResponseDate"), deadline_value)
            deadline_text = "Estimated forecast deadline; verify when the opportunity is posted. " + deadline_text
            warnings.append("Forecasted opportunity: funding, eligibility and dates may change; applications may not be open.")
        deadline = parse_date(deadline_value)
        if deadline is None:
            warnings.append("Application deadline is unknown; verify the official announcement and any recurring dates.")
        if deadline_value and deadline is None:
            deadline_text = f"{deadline_text} {plain_text(deadline_value)}".strip()
        award_min = parse_amount(first(synopsis.get("awardFloor"), synopsis.get("awardFloorFormatted")))
        award_max = parse_amount(first(synopsis.get("awardCeiling"), synopsis.get("awardCeilingFormatted")))
        if award_min is not None and award_max is not None and award_min > award_max:
            award_min = award_max = None
            warnings.append("Official award minimum exceeds maximum; amounts require review.")
        if award_min == 0 or award_max == 0:
            warnings.append("The source lists a zero award boundary; confirm whether this means unspecified funding.")
        # Total program funding / expected awards are deliberately not treated as a typical award.
        agency = synopsis.get("agencyDetails") or raw.get("agencyDetails") or {}
        # The legacy synopsis.agencyName field sometimes contains a grants
        # officer's name; structured agencyDetails is the funder authority.
        funder = plain_text(first(agency.get("agencyName"),
                                  search.get("agency"), search.get("agencyName"), raw.get("agencyName"))) or "Unknown"
        application_url = public_link(first(raw.get("assistURL"), raw.get("applicationUrl")))
        requirements = []
        for folder in raw.get("synopsisAttachmentFolders") or []:
            for attachment in folder.get("synopsisAttachments") or []:
                label = plain_text(first(attachment.get("fileDescription"), attachment.get("fileName")))
                if label:
                    requirements.append(f"Announcement attachment (review for requirements): {label}")
        if not requirements:
            warnings.append("Required application materials have not been extracted; review the official announcement.")
        categories = descriptions(synopsis.get("fundingActivityCategories"))
        programs = descriptions(raw.get("alns") or raw.get("cfdas"))
        programs += [v for v in descriptions(synopsis.get("fundingInstruments")) if v not in programs]
        contact = "; ".join(dict.fromkeys(plain_text(synopsis.get(key)) for key in
                           ["agencyContactName", "agencyContactEmail", "agencyContactPhone", "agencyContactDesc"]
                           if synopsis.get(key)))
        cost_sharing = synopsis.get("costSharing")
        if not isinstance(cost_sharing, bool):
            cost_sharing = {"true": True, "false": False, "yes": True, "no": False}.get(str(cost_sharing).lower())
        return GrantRecord(source=self.name, source_id=source_id,
            source_url=f"https://www.grants.gov/search-results-detail/{source_id}",
            application_url=application_url, funder_name=funder, grant_title=title,
            description=description, eligibility_text=eligibility_text, applicant_types=applicant_types,
            geographic_restrictions=[], geography_scope="unknown", populations_served=[],
            categories=categories, program_areas=programs, award_min=award_min, award_max=award_max,
            estimated_award=None, open_date=parse_date(first(synopsis.get("postingDateStr"),
                synopsis.get("postingDate"), search.get("openDate"), raw.get("openDate"))),
            deadline=deadline, deadline_text=deadline_text.strip(), grant_status=status,
            application_requirements=requirements, contact_information=contact,
            matching_funds_required=cost_sharing, last_checked=datetime.now(timezone.utc),
            raw_text="\n".join([title, description, eligibility_text, deadline_text, *categories, *programs]),
            warnings=warnings)
