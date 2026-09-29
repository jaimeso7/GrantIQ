"""The public source tree must start without private research materials."""
import shutil
from pathlib import Path
from test_app import factory, client
from grantiq.app.services import research_context
from grantiq.app.services.repository import get_profile


def test_public_defaults_do_not_prevent_later_private_import(factory, tmp_path, monkeypatch):
    shutil.copytree(research_context.ROOT / "config" / "examples", tmp_path / "config" / "examples")
    monkeypatch.setattr(research_context, "ROOT", tmp_path)
    with factory() as session:
        research_context.seed_prospects(session)
        assert get_profile(session).excluded_funders == []
        assert research_context.existing_funders()["funders"] == []
        (tmp_path / "config" / "existing_funders.json").write_text(
            '{"funders":[{"name":"Fictional Test Funder","aliases":[]}]}', encoding="utf-8")
        research_context.seed_prospects(session)
        assert get_profile(session).excluded_funders == ["Fictional Test Funder"]


def test_absent_private_source_documents_return_not_found(client, tmp_path, monkeypatch):
    from grantiq.app.routes import prospects
    monkeypatch.setattr(prospects, "ROOT", tmp_path)
    assert client.get("/research-documents/ranking").status_code == 404
    assert client.get("/research-documents/keywords").status_code == 404
    response = client.get("/research")
    assert response.status_code == 200
    assert 'href="/research-documents/ranking"' not in response.text
