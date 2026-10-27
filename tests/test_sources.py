"""Contract tests for public API normalization and controlled source retrieval."""
from datetime import date
import hashlib
import json
from pathlib import Path
import socket

import httpx
import pytest

from grantiq.app.sources.base import SourceError
from grantiq.app.sources.grants_gov import GrantsGovSource, parse_amount, parse_date
from grantiq.app.sources.generic_scraper import (GenericPageSource, ListingPageSource, PublicOnlyTransport,
                                                 parse_date_window, validate_public_url, window_status)


@pytest.fixture
def official_detail():
    return {"id": 12345, "opportunityTitle": "Community vision health", "ost": "POSTED",
        "agencyDetails": {"agencyName": "Example Federal Agency"}, "synopsis": {
            "synopsisDesc": "<p>Eye care for children and adults.</p><script>alert(1)</script>",
            "applicantTypes": [{"id": "12", "description": "Nonprofits having a 501(c)(3) status with the IRS"}],
            "applicantEligibilityDesc": "See full eligibility criteria.",
            "awardFloor": "5,000", "awardCeiling": "25,000", "costSharing": False,
            "postingDateStr": "2026-09-01-00-00-00", "responseDateStr": "2026-11-30-00-00-00",
            "responseDateDesc": "Applications are due at 5 PM Eastern.",
            "fundingActivityCategories": [{"id": "HL", "description": "Health"}],
            "fundingInstruments": [{"id": "G", "description": "Grant"}],
            "agencyContactEmail": "grants@example.org"},
        "cfdas": [{"programTitle": "Community health"}], "assistURL": "https://apply.example.org/12345"}


def test_official_response_normalization(official_detail):
    with GrantsGovSource(min_interval=0) as source:
        record = source.normalize_grant({"errorcode": 0, "data": official_detail})
    assert record.source_id == "12345"
    assert record.grant_title == "Community vision health"
    assert record.description == "Eye care for children and adults."
    assert record.applicant_types[0].startswith("Nonprofits")
    assert record.award_min == 5000 and record.award_max == 25000
    assert record.estimated_award is None
    assert record.matching_funds_required is False
    assert record.deadline == date(2026, 11, 30)
    assert record.open_date == date(2026, 9, 1)
    assert record.program_areas == ["Community health", "Grant"]
    assert record.categories == ["Health"]
    assert record.grant_status == "posted"
    assert record.application_url == "https://apply.example.org/12345"
    assert record.last_checked.tzinfo is not None
    # Federal sponsorship and the word "community" do not prove geography.
    assert record.geography_scope == "unknown" and record.geographic_restrictions == []
    assert record.populations_served == []


def test_forecast_estimated_dates_and_missing_data():
    with GrantsGovSource(min_interval=0) as source:
        record = source.normalize_grant({"id": 361394, "opportunityTitle": "Vision research",
            "docType": "forecast", "forecast": {"forecastDesc": "Future vision research awards.",
            "postingDate": "Mar 03, 2026 12:00:00 AM EST",
            "estApplicationResponseDate": "Sep 25, 2026 12:00:00 AM EDT"}})
    assert record.grant_status == "forecasted"
    assert record.deadline == date(2026, 9, 25)
    assert "Estimated" in record.deadline_text
    assert record.award_max is None
    assert record.application_url is None
    assert record.funder_name == "Unknown"
    assert any("Applicant types" in message for message in record.warnings)


def test_zero_awards_are_not_replaced_by_funding_totals(official_detail):
    official_detail["synopsis"].update(awardFloor=0, awardCeiling="0", estimatedFunding="1000000", expectedNumberOfAwards="5")
    with GrantsGovSource(min_interval=0) as source:
        record = source.normalize_grant(official_detail)
    assert record.award_min == record.award_max == 0
    assert record.estimated_award is None
    assert any("zero award" in message for message in record.warnings)


def test_structured_funder_overrides_legacy_contact_name(official_detail):
    official_detail["synopsis"]["agencyName"] = "Teresa Example, Grants Officer"
    with GrantsGovSource(min_interval=0) as source:
        record = source.normalize_grant(official_detail)
    assert record.funder_name == "Example Federal Agency"


def test_invalid_award_range_flagged_and_unsafe_application_url_discarded(official_detail):
    official_detail["synopsis"].update(awardFloor="100", awardCeiling="10")
    official_detail["assistURL"] = "javascript:alert(1)"
    with GrantsGovSource(min_interval=0) as source:
        record = source.normalize_grant(official_detail)
    assert record.award_min is record.award_max is None
    assert record.application_url is None
    assert any("minimum exceeds maximum" in message for message in record.warnings)


def test_search_pagination_deduplication_and_full_detail(official_detail):
    offsets = []
    fetched_ids = []

    def respond(request):
        payload = json.loads(request.content)
        if request.url.path.endswith("search2"):
            offset = payload["startRecordNum"]
            offsets.append(offset)
            assert payload["oppStatuses"] == "forecasted|posted"
            ids = [12345, 12346] if offset == 0 else [12346, 12347]
            return httpx.Response(200, json={"errorcode": 0, "data": {"hitCount": 4,
                "oppHits": [{"id": str(i), "title": f"Search title {i}", "oppStatus": "posted"} for i in ids]}})
        number = payload["opportunityId"]
        fetched_ids.append(number)
        return httpx.Response(200, json={"errorcode": 0, "data": {**official_detail, "id": number}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = GrantsGovSource(["vision"], page_size=2, max_records=10, client=client, min_interval=0)
        records = list(source.fetch_grants())
    assert offsets == [0, 2]
    assert fetched_ids == [12345, 12346, 12347]
    assert len(records) == 3
    assert all(record.description for record in records)
    assert source.stats["http_requests"] == 5
    assert not source.errors


def test_retry_then_cap_warning(official_detail):
    attempts = 0
    sleeps = []

    def respond(request):
        nonlocal attempts
        if request.url.path.endswith("search2"):
            attempts += 1
            if attempts == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"data": {"hitCount": 20, "oppHits": [{"id": "12345"}]}})
        return httpx.Response(200, json={"data": official_detail})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = GrantsGovSource(["vision"], max_records=1, client=client, min_interval=0, sleep=sleeps.append)
        records = list(source.fetch_grants())
    assert len(records) == 1
    assert sleeps == [1]
    assert source.stats["http_retries"] == 1
    assert source.stats["truncated"] is True
    assert any("bounded subset" in message for message in source.errors)


def test_detail_failure_does_not_emit_partial_record():
    def respond(request):
        if request.url.path.endswith("search2"):
            return httpx.Response(200, json={"data": {"hitCount": 1,
                "oppHits": [{"id": "12345", "title": "Partial"}]}})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = GrantsGovSource(["vision"], client=client, min_interval=0)
        assert list(source.fetch_grants()) == []
    assert source.stats["rejected"] == 1
    assert "detail/normalization failed" in source.errors[0]


def test_repeated_upstream_pages_stop_pagination(official_detail):
    def respond(request):
        if request.url.path.endswith("search2"):
            return httpx.Response(200, json={"data": {"hitCount": 10000,
                "oppHits": [{"id": "12345", "title": "Partial"}]}})
        return httpx.Response(200, json={"data": official_detail})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = GrantsGovSource(["vision"], client=client, min_interval=0)
        assert len(list(source.fetch_grants())) == 1
    assert source.stats["http_requests"] == 3
    assert "repeated a previously returned page" in source.errors[0]


@pytest.mark.parametrize("payload", [{"errorcode": 1, "data": {}}, {"data": None}, {"data": {}}])
def test_malformed_api_response_reported(payload):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        source = GrantsGovSource(["vision"], client=client, min_interval=0)
        assert list(source.fetch_grants()) == []
    assert source.errors


def test_temporary_transport_failures_exhaust_bounded_retries():
    def respond(request):
        raise httpx.ConnectError("network unavailable", request=request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = GrantsGovSource(["vision"], client=client, min_interval=0, sleep=lambda _: None)
        assert list(source.fetch_grants()) == []
    assert source.stats["http_requests"] == 3
    assert source.stats["http_failures"] == 1
    assert source.errors


@pytest.mark.parametrize("value, expected", [("$25,000", 25000), (0, 0), ("Unknown", None),
                                            ("NaN", None), ("Infinity", None), (-5, None)])
def test_amount_parsing(value, expected):
    assert parse_amount(value) == expected


def public_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def private_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]


@pytest.mark.parametrize("url", ["http://example.org/grants", "https://user:pass@example.org",
                                 "https://example.org:8443/grants", "file:///etc/passwd"])
def test_url_shape_security(url):
    with pytest.raises(SourceError):
        validate_public_url(url, resolver=public_dns)


def test_private_dns_destination_rejected():
    with pytest.raises(SourceError):
        validate_public_url("https://approved.example.org/grants", resolver=private_dns)


def test_dns_address_is_pinned_with_original_tls_hostname():
    requests = []
    transport = PublicOnlyTransport(resolver=public_dns,
        transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, text="OK")))
    with httpx.Client(transport=transport) as client:
        assert client.get("https://approved.example.org/grants").text == "OK"
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["Host"] == "approved.example.org"
    assert requests[0].extensions["sni_hostname"] == "approved.example.org"


def test_approved_page_clean_extraction_and_cache(tmp_path):
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\nCrawl-delay: 2")
        return httpx.Response(200, headers={"Content-Type": "text/html"}, text='''<h1>Community Health Grant</h1>
          <main>Funding for community health and accessible vision care services.<script>steal()</script></main>
          <time class="deadline" datetime="2026-12-01">December 1</time><a class="apply" href="/apply">Apply</a>''')

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = GenericPageSource("Example Foundation", "https://example.org/grant", terms_reviewed=True,
            client=client, resolver=public_dns, min_interval=0, sleep=lambda _: None, cache_dir=tmp_path,
            selectors={"deadline": ".deadline", "application_url": "a.apply"})
        first_record = list(source.fetch_grants())[0]
        cached_record = list(source.fetch_grants())[0]
    assert len(requests) == 2
    assert "steal()" not in first_record.description
    assert first_record.deadline == date(2026, 12, 1)
    assert first_record.application_url == "https://example.org/apply"
    assert first_record.grant_status == "unknown"
    assert first_record.geographic_restrictions == []
    assert first_record.last_checked == cached_record.last_checked
    assert source.min_interval == 2


@pytest.mark.parametrize("robots_status, robots_text", [(200, "User-agent: *\nDisallow: /"),
                    (404, ""), (200, "<html>Access denied</html>"), (302, "")])
def test_robots_fail_closed(robots_status, robots_text):
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(robots_status, text=robots_text, headers={"Location": "https://example.org/login"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = GenericPageSource("Example Foundation", "https://example.org/grant", terms_reviewed=True,
                                   client=client, resolver=public_dns, min_interval=0)
        assert list(source.fetch_grants()) == []
    assert len(requests) == 1
    assert source.errors


def test_terms_review_is_required_before_any_network_request():
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("No network request permitted"))) as client:
        source = GenericPageSource("Example", "https://example.org/grant", client=client, resolver=public_dns)
        assert list(source.fetch_grants()) == []
    assert "terms_reviewed" in source.errors[0]


def test_oversized_page_is_rejected():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="x" * 200))) as client:
        source = GenericPageSource("Example", "https://example.org/grant", terms_reviewed=True,
            client=client, resolver=public_dns, max_response_bytes=100, min_interval=0)
        assert list(source.fetch_grants()) == []
    assert "size limit" in source.errors[0]


# --- Listing pages: several opportunities on one approved page ----------------

FIXTURE = Path(__file__).parent / "fixtures" / "jaxcf_listing.html"
LISTING_URL = "https://example.org/apply-for-grants/"
ALLOW_ALL = "User-agent: *\nDisallow:\nCrawl-delay: 10"


def listing_responder(page=None, robots=ALLOW_ALL, robots_status=200, calls=None):
    """Serve robots.txt and the listing page; fail loudly on any other URL."""
    body = FIXTURE.read_text(encoding="utf-8") if page is None else page

    def respond(request):
        if calls is not None:
            calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(robots_status, text=robots)
        if str(request.url) == LISTING_URL:
            return httpx.Response(200, headers={"Content-Type": "text/html"}, text=body)
        pytest.fail(f"Listing adapter must not fetch {request.url}")

    return respond


def listing_source(client, tmp_path, **kwargs):
    kwargs.setdefault("today", date(2026, 12, 1))
    return ListingPageSource("Example Community Foundation", LISTING_URL, terms_reviewed=True,
                             client=client, resolver=public_dns, min_interval=0,
                             sleep=lambda _: None, cache_dir=tmp_path, **kwargs)


def reordered_with_renamed_row(original: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(original.replace("Riverbend Early Learning", "Riverbend Early Learning Initiative"),
                         "html.parser")
    container = soup.select_one("div.e-n-accordion")
    for row in reversed(container.select("details.e-n-accordion-item")):
        container.append(row.extract())
    return str(soup)


def test_listing_page_emits_one_record_per_row_with_distinct_source_ids(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(listing_responder())) as client:
        records = list(listing_source(client, tmp_path).fetch_grants())
    assert len(records) == 5
    assert len({record.source_id for record in records}) == 5
    # The single-page adapter keys identity on the URL; every row would collapse into one grant.
    assert hashlib.sha256(LISTING_URL.encode()).hexdigest() not in {r.source_id for r in records}
    assert {r.source_url for r in records} == {LISTING_URL}


def test_listing_source_ids_survive_row_reordering_and_title_edits(tmp_path):
    original = FIXTURE.read_text(encoding="utf-8")
    with httpx.Client(transport=httpx.MockTransport(listing_responder(original))) as client:
        before = {r.source_id for r in listing_source(client, tmp_path).fetch_grants()}
    variant = reordered_with_renamed_row(original)
    with httpx.Client(transport=httpx.MockTransport(listing_responder(variant))) as client:
        after = {r.source_id for r in listing_source(client, tmp_path / "second").fetch_grants()}
    assert before == after


def test_date_range_without_leading_year_infers_it_from_the_closing_date():
    opens, closes, prose = parse_date_window("Application is open January 5 – March 3, 2027.")
    assert (opens, closes) == (date(2027, 1, 5), date(2027, 3, 3))
    assert prose == "Application is open January 5 – March 3, 2027."


def test_range_crossing_new_year_rolls_the_opening_year_back():
    opens, closes, _ = parse_date_window("Application is open November 3 – January 15, 2027.")
    assert (opens, closes) == (date(2026, 11, 3), date(2027, 1, 15))


def test_range_with_no_year_anywhere_stays_unknown():
    opens, closes, prose = parse_date_window("Applications open January 5 – March 3.")
    assert opens is None and closes is None
    # The prose survives for staff even though no date could be trusted.
    assert prose == "Applications open January 5 – March 3."


def test_month_without_a_day_is_never_read_as_a_date():
    assert parse_date_window("The next grant cycle will open in 2028.") == (None, None, "")


@pytest.mark.parametrize("today, expected", [(date(2026, 10, 1), "forecasted"),
                                             (date(2026, 12, 1), "posted"),
                                             (date(2027, 2, 1), "closed")])
def test_application_window_maps_to_status(today, expected):
    assert window_status(date(2026, 11, 3), date(2027, 1, 15), today) == expected


def test_rolling_row_scores_as_open_without_a_fabricated_deadline(tmp_path):
    from grantiq.app.schemas import OrganizationProfile
    from grantiq.app.services.scoring import score_grant

    class Embedder:
        backend_name = "test"

        def similarity(self, left, right):
            return 0.5

    with httpx.Client(transport=httpx.MockTransport(listing_responder())) as client:
        records = list(listing_source(client, tmp_path).fetch_grants())
    rolling = next(r for r in records if r.grant_title == "Public Art Sponsorships")
    assert rolling.deadline is None and rolling.grant_status == "posted"
    assessment = score_grant(rolling, OrganizationProfile(mission="vision care", programs=["vision care"],
                                                          service_locations=["Jacksonville, Florida"]),
                             today=date(2026, 12, 1), embedder=Embedder())
    readiness = next(c for c in assessment.components if c.key == "readiness")
    assert readiness.points == 4.0  # the rolling rule fires on deadline_text, not a guessed date


def test_applicant_budget_cap_is_not_recorded_as_an_award_amount(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(listing_responder())) as client:
        records = list(listing_source(client, tmp_path).fetch_grants())
    capped = next(r for r in records if r.grant_title == "Small Organizations")
    assert capped.award_min is None and capped.award_max is None
    assert "$150,000" in capped.eligibility_text
    assert any("$150,000" in warning for warning in capped.warnings)


def test_county_named_in_the_row_is_recorded_and_others_stay_unknown(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(listing_responder())) as client:
        records = list(listing_source(client, tmp_path).fetch_grants())
    by_title = {r.grant_title: r for r in records}
    assert by_title["Riverbend Early Learning"].geographic_restrictions == ["Example County"]
    assert by_title["Riverbend Early Learning"].geography_scope == "local"
    assert by_title["Public Art Sponsorships"].geographic_restrictions == []
    assert by_title["Public Art Sponsorships"].geography_scope == "unknown"


def test_configured_geography_is_flagged_as_asserted_not_read(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(listing_responder())) as client:
        records = list(listing_source(client, tmp_path, defaults={
            "geographic_restrictions": ["Duval County"], "geography_scope": "local"}).fetch_grants())
    asserted = next(r for r in records if r.grant_title == "Public Art Sponsorships")
    assert asserted.geographic_restrictions == ["Duval County"]
    assert any("asserted by an administrator" in warning for warning in asserted.warnings)


def test_missing_container_selector_reports_an_error_and_yields_nothing(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(listing_responder())) as client:
        source = listing_source(client, tmp_path, selectors={"row": "section.not-present"})
        assert list(source.fetch_grants()) == []
    # Silence here would report a clean run while staff conclude there are no local grants.
    assert "section.not-present" in source.errors[0]
    assert source.stats["rejected"] >= 1 and source.stats["rows_matched"] == 0


def test_one_unparseable_row_does_not_drop_the_others(tmp_path):
    broken = FIXTURE.read_text(encoding="utf-8").replace(
        '<h6 class="e-n-accordion-item-title-text">Small Organizations</h6>', "")
    with httpx.Client(transport=httpx.MockTransport(listing_responder(broken))) as client:
        source = listing_source(client, tmp_path)
        records = list(source.fetch_grants())
    assert len(records) == 4
    assert len(source.errors) == 1 and "row 4" in source.errors[0]


def test_row_count_cap_rejects_an_overbroad_selector(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(listing_responder())) as client:
        source = listing_source(client, tmp_path, selectors={"row": "p"}, max_rows=3)
        assert list(source.fetch_grants()) == []
    assert "above the 3-row cap" in source.errors[0]


def test_listing_source_honors_robots_terms_and_caches(tmp_path):
    calls = []
    with httpx.Client(transport=httpx.MockTransport(listing_responder(calls=calls))) as client:
        source = listing_source(client, tmp_path)
        first = list(source.fetch_grants())
        cached = list(source.fetch_grants())
    assert len(calls) == 2  # robots.txt and the listing page, nothing else, even twice over
    assert source.min_interval == 10  # crawl delay adopted from robots.txt
    assert [r.source_id for r in first] == [r.source_id for r in cached]
    assert first[0].last_checked == cached[0].last_checked


def test_listing_source_refuses_when_robots_disallows(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(
            listing_responder(robots="User-agent: *\nDisallow: /"))) as client:
        source = listing_source(client, tmp_path)
        assert list(source.fetch_grants()) == []
    assert source.errors


def test_listing_source_requires_terms_review_before_any_request(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(
            lambda _: pytest.fail("No network request permitted"))) as client:
        source = ListingPageSource("Example", LISTING_URL, client=client, resolver=public_dns,
                                   min_interval=0, cache_dir=tmp_path)
        assert list(source.fetch_grants()) == []
    assert "terms_reviewed" in source.errors[0]


def test_detail_fetching_is_refused_until_implemented(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(
            lambda _: pytest.fail("No network request permitted"))) as client:
        source = listing_source(client, tmp_path, allow_detail_fetch=True)
        assert list(source.fetch_grants()) == []
    assert "not implemented" in source.errors[0]


def test_invalid_selector_is_rejected_at_construction(tmp_path):
    with pytest.raises(SourceError, match="selector"):
        ListingPageSource("Example", LISTING_URL, selectors={"row": "details["}, cache_dir=tmp_path)


def test_parser_map_resolves_to_real_adapter_classes():
    from grantiq.app.sources import generic_scraper
    from grantiq.ingestion import PARSERS
    assert set(PARSERS) == {"generic", "listing"}
    for name in PARSERS.values():
        assert isinstance(getattr(generic_scraper, name), type)


def test_configured_crawl_delay_is_honored_when_robots_hides_it(tmp_path):
    """Sites sometimes put Crawl-delay above their first User-agent line, where a
    spec-compliant parser ignores it. An administrator can still set the floor."""
    from grantiq.app.sources.generic_scraper import ListingScraperSource
    orphaned = "Crawl-delay: 10\nUser-agent: *\nDisallow:"
    with httpx.Client(transport=httpx.MockTransport(listing_responder(robots=orphaned))) as client:
        item = {"name": "Example", "url": LISTING_URL, "terms_reviewed": True, "min_interval": 10}
        source = ListingScraperSource(item, client=client, resolver=public_dns,
                                      sleep=lambda _: None, cache_dir=tmp_path, today=date(2026, 12, 1))
        assert len(list(source.fetch_grants())) == 5
    assert source.min_interval == 10
