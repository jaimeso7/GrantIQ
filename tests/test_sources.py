"""Contract tests for public API normalization and controlled source retrieval."""
from datetime import date
import json
import socket

import httpx
import pytest

from grantiq.app.sources.base import SourceError
from grantiq.app.sources.grants_gov import GrantsGovSource, parse_amount, parse_date
from grantiq.app.sources.generic_scraper import GenericPageSource, PublicOnlyTransport, validate_public_url


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
