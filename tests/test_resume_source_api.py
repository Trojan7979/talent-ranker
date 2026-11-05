from types import SimpleNamespace
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sieve_app import resume_api
from tests.auth_support import FakeRecruiterIdentity
from talent_ranker.storage import DriveFile

URL = "https://contoso.sharepoint.com/sites/Recruiting/Resumes/jane.pdf"


@pytest.fixture
def source_client(monkeypatch):
    state = SimpleNamespace(
        row={"source_uri": "sharepoint://DriveID/ItemID", "source_etag": "v1"},
        file=DriveFile("ItemID", "jane.pdf", web_url=URL, etag="v1"),
        error=None, calls=[],
    )

    class Store:
        def get_candidate_source(self, candidate_id):
            assert candidate_id == "CAND_0001"
            return state.row

    class Source:
        def get_file(self, source_uri):
            state.calls.append(source_uri)
            if state.error:
                raise state.error
            return state.file

    monkeypatch.setattr(resume_api, "_configured", lambda: None)
    monkeypatch.setattr(resume_api, "configured_sharepoint_source", lambda _: Source())
    app = FastAPI()
    app.state.index_store = Store()
    app.state.screening_settings = SimpleNamespace(recruiter_tokens={"secret": "recruiter"})
    app.state.recruiter_identity = FakeRecruiterIdentity()
    app.state.agent_settings = SimpleNamespace(workspace_id="demo")
    app.state.ranking_service = SimpleNamespace(state=SimpleNamespace(
        pipeline=SimpleNamespace(repo=SimpleNamespace(
            accessible_candidate_ids=lambda ids, scope: set(ids)
        ))
    ))
    app.include_router(resume_api.router)
    with TestClient(app) as client:
        yield client, state


def fetch(client, candidate_id="CAND_0001"):
    return client.get(f"/api/sources/candidates/{candidate_id}/resume",
                      headers={"Cookie": "sieve_recruiter_session=secret"})


def test_source_lookup_requires_recruiter_access_before_calling_sharepoint(source_client):
    client, state = source_client
    path = "/api/sources/candidates/CAND_0001/resume"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Cookie": "sieve_recruiter_session=wrong"}).status_code == 401
    assert not state.calls
    assert fetch(client, "invalid").status_code == 422


@pytest.mark.parametrize("stored_tag,expected", [("v1", "unchanged"), ("v0", "changed"), (None, "unknown")])
def test_lookup_returns_current_browser_link_and_version_comparison(source_client, stored_tag, expected):
    client, state = source_client
    state.row["source_etag"] = stored_tag
    response = fetch(client)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "file_name": "jane.pdf", "web_url": URL, "modified_at": "",
        "provider": "sharepoint", "source_status": expected,
    }
    assert state.calls == ["sharepoint://DriveID/ItemID"]


@pytest.mark.parametrize("row", [None, {"source_uri": "file:///private/resume.pdf"}])
def test_unlinked_or_inactive_candidate_has_no_source_link(source_client, row):
    client, state = source_client
    state.row = row
    assert fetch(client).status_code == 404
    assert not state.calls


@pytest.mark.parametrize("upstream,expected", [(403, 404), (404, 404), (410, 404), (401, 502), (429, 502), (500, 502)])
def test_sharepoint_failures_never_expose_upstream_details(source_client, upstream, expected):
    client, state = source_client
    response = requests.Response()
    response.status_code = upstream
    state.error = requests.HTTPError("secret token or private path", response=response)
    result = fetch(client)
    assert result.status_code == expected
    assert "secret" not in result.text


def test_timeout_and_missing_browser_link_are_recoverable(source_client):
    client, state = source_client
    state.error = requests.Timeout("sensitive request URL")
    assert fetch(client).status_code == 502
    state.error = None
    state.file = DriveFile("ItemID", "jane.pdf")
    assert fetch(client).status_code == 502


def test_drive_original_is_resolved_for_indexed_resume(source_client, monkeypatch):
    client, state = source_client
    state.row = {"source_uri": "gdrive://resume_123", "source_etag": None,
                 "source_md5_checksum": "stored-md5"}
    url = "https://drive.google.com/file/d/resume_123/view"

    class DriveSource:
        def get_file(self, source_uri):
            assert source_uri == "gdrive://resume_123"
            return DriveFile("resume_123", "mine.pdf", web_url=url,
                             md5_checksum="stored-md5")

    monkeypatch.setattr(resume_api, "require_token", lambda actor: Path("recruiter-token.json"))
    monkeypatch.setattr(resume_api, "configured_drive_source", lambda **kwargs: DriveSource())
    result = fetch(client)
    assert result.status_code == 200
    assert result.json()["web_url"] == url
    assert result.json()["provider"] == "google_drive"
    assert result.json()["source_status"] == "unchanged"


def test_drive_checksum_detects_changed_file(source_client, monkeypatch):
    client, state = source_client
    state.row = {"source_uri": "gdrive://resume_123", "source_etag": None,
                 "source_md5_checksum": "old-md5"}
    monkeypatch.setattr(resume_api, "require_token", lambda actor: Path("recruiter-token.json"))
    monkeypatch.setattr(resume_api, "configured_drive_source", lambda **kwargs: SimpleNamespace(
        get_file=lambda _: DriveFile("resume_123", "mine.pdf",
                                     web_url="https://drive.google.com/file/d/resume_123/view",
                                     md5_checksum="new-md5"),
    ))
    assert fetch(client).json()["source_status"] == "changed"
