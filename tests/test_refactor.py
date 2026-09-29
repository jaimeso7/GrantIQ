"""Regression checks for request-local indexing and bounded database work."""
import pytest
import json
from sqlalchemy import event

from test_app import factory, client, record, seed, FixedEmbedder
from grantiq.app.services import research_context
from grantiq.app.services.repository import get_profile, set_profile, rescore_all


@pytest.fixture(autouse=True)
def synthetic_research(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    fixtures = {
        "existing_funders.json": {"funders": [{"name": "Example Funder", "aliases": ["Example Foundation"]}]},
        "research_prospects.json": [],
        "search_keywords.json": {"groups": [{"area": "Sample", "terms": [f"topic {i}" for i in range(30)]}]},
    }
    for filename, data in fixtures.items():
        (config / filename).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(research_context, "ROOT", tmp_path)


def test_staff_index_reads_config_once_and_profile_edit_invalidates_it(factory, record, monkeypatch):
    with factory() as session:
        research_context.seed_prospects(session)
        reads = []
        original = research_context.existing_funders

        def load():
            reads.append(1)
            return original()

        monkeypatch.setattr(research_context, "existing_funders", load)
        walmart = record.model_copy(update={"funder_name": "Example Foundation"})
        for _ in range(100):
            assert research_context.staff_context(session, walmart)["hidden"]
        assert len(reads) == 1
        profile = get_profile(session)
        profile.excluded_funders.remove("Example Funder")
        set_profile(session, profile)
        assert research_context.staff_context(session, walmart) is None
        assert len(reads) == 2


def test_staff_index_does_not_leak_between_organizations(factory, record):
    with factory() as first:
        research_context.seed_prospects(first)
        walmart = record.model_copy(update={"funder_name": "Example Funder"})
        assert research_context.staff_context(first, walmart)["hidden"]
    with factory() as second:
        profile = get_profile(second)
        profile.excluded_funders = []
        set_profile(second, profile)
        assert research_context.staff_context(second, walmart) is None


def test_keyword_batches_deduplicate_case_and_respect_core_only_size(factory):
    with factory() as session:
        profile = get_profile(session)
    profile.funding_interests = [" Eye Health ", "NEW TOPIC", "new topic", " "]
    batch, _, _ = research_context.keyword_plan(profile)
    assert len(batch) == len({value.casefold() for value in batch})
    assert batch.count("NEW TOPIC") == 1
    batch, position, _ = research_context.keyword_plan(profile, position=7, size=6)
    assert batch == research_context.CORE_TERMS and position == 7
    with pytest.raises(ValueError):
        research_context.keyword_plan(profile, size=5)


def test_bulk_rescore_fetches_relationships_in_batches(factory, record):
    for index in range(12):
        seed(factory, record.model_copy(update={"source_id": str(index), "grant_title": f"Eye care {index}"}))
    engine = factory.kw["bind"]
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with factory() as session:
        profile = get_profile(session)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            rescore_all(session, profile, embedder=FixedEmbedder())
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) <= 4, "Rescoring should not issue relationship queries per grant."


def test_presentation_routes_and_access_controls(client, tmp_path, monkeypatch):
    from grantiq.app.routes import presentation
    monkeypatch.setattr(presentation, "ROOT", tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "public-overview.html").write_text("<h1>Public overview</h1>", encoding="utf-8")
    assert client.get("/sprint-review").status_code == 200
    assert client.get("/sprint-review/handout").status_code == 404
    (docs / "sprint-review.pdf").write_bytes(b"%PDF-test-fixture")
    assert client.get("/sprint-review/handout").content.startswith(b"%PDF")
    assert client.get("/sprint-review/other-file").status_code == 404
    client.app.state.password = "test-only-password"
    for path in ("/sprint-review", "/sprint-review/handout"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login"
