from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from sieve_app import drive_account, drive_api, indexing_worker
from sieve_app.indexing_worker import IndexingWorker
from tests.auth_support import FakeRecruiterIdentity
from talent_ranker.drive_links import drive_id
from talent_ranker.drive_source import DriveResumeSource
from talent_ranker.storage import DriveFile


def test_drive_links_select_one_file_or_a_folder():
    file_url = "https://drive.google.com/file/d/resume_123/view"
    folder_url = "https://drive.google.com/drive/folders/team_456"
    assert drive_id(file_url, "file") == "resume_123"
    assert drive_id(folder_url, "folder") == "team_456"
    with pytest.raises(ValueError):
        drive_id("https://other.example/file/d/resume_123/view", "file")

    class Store:
        def get_resume(self, file_id):
            assert file_id == "resume_123"
            return DriveFile(file_id, "mine.pdf")

        def list_resumes(self, folder_id):
            assert folder_id == "team_456"
            return [DriveFile("resume_123", "mine.pdf"), DriveFile("other", "other.docx")]

    source = DriveResumeSource(Store())
    assert [item.name for item in source.list_resumes(file_url)] == ["mine.pdf"]
    assert len(source.list_resumes(folder_url)) == 2


def test_recruiter_drive_connection_never_falls_back_to_shared_token(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_account.SETTINGS, "google_token_file", str(tmp_path / "legacy.json"))
    (tmp_path / "legacy.json").write_text("{}", encoding="utf-8")
    first, second = str(uuid4()), str(uuid4())
    first_path = drive_account.token_file(first)
    assert first_path != drive_account.token_file(second)
    with pytest.raises(HTTPException) as missing_first:
        drive_account.require_token(first)
    assert missing_first.value.status_code == 503
    first_path.parent.mkdir()
    first_path.write_text("{}", encoding="utf-8")
    assert drive_account.require_token(first) == first_path
    with pytest.raises(HTTPException) as missing_second:
        drive_account.require_token(second)
    assert missing_second.value.status_code == 503


def test_drive_preview_and_analysis_use_recruiter_review_queue(monkeypatch):
    file_url = "https://drive.google.com/file/d/resume_123/view"
    submitted = []

    class Source:
        def list_resumes(self, location):
            assert location == file_url
            return [DriveFile("resume_123", "mine.pdf", web_url=file_url)]

    class Jobs:
        def submit_analysis(self, request_id, location, actor):
            submitted.append((location, actor))
            return {"id": uuid4(), "status": "pending", "entries": [], "discovered": 0,
                    "indexed": 0, "skipped": 0, "failures": []}

    monkeypatch.setattr(drive_api, "require_token", lambda actor: Path("recruiter-token.json"))
    monkeypatch.setattr(drive_api, "configured_drive_source", lambda **kwargs: Source())
    app = FastAPI()
    app.state.recruiter_identity = FakeRecruiterIdentity()
    app.state.index_store = Jobs()
    app.include_router(drive_api.router)
    with TestClient(app) as client:
        assert client.post("/api/sources/drive/preview", json={"location": file_url}).status_code == 401
        headers = {"Cookie": "sieve_recruiter_session=secret"}
        preview = client.post("/api/sources/drive/preview", json={"location": file_url},
                              headers=headers)
        assert preview.status_code == 200
        assert [file["name"] for file in preview.json()["files"]] == ["mine.pdf"]
        analyzed = client.post("/api/sources/drive/analyze", headers=headers,
                               json={"location": file_url, "request_id": str(uuid4())})
        assert analyzed.status_code == 202
        assert submitted == [(file_url, "recruiter")]


def test_drive_indexing_job_uses_selected_file_and_persists_drive_source(monkeypatch):
    file_url = "https://drive.google.com/file/d/resume_123/view"

    class Source:
        def list_resumes(self, location):
            assert location == file_url
            return [DriveFile("resume_123", "mine.pdf")]

        def download(self, file_id, destination):
            assert file_id == "resume_123"
            destination.write_bytes(b"resume")

        def source_uri(self, file_id):
            return f"gdrive://{file_id}"

    class Pipeline:
        def ingest_resume(self, candidate_id, path, source_uri, metadata, scope=None):
            assert candidate_id == "CAND_0001"
            assert path.suffix == ".pdf"
            assert source_uri == metadata["client_source_uri"] == "gdrive://resume_123"
            assert scope.actor_id == "recruiter"

    class Jobs:
        def __init__(self):
            self.identity = None
            self.result = None

        def claim_next(self):
            return {"id": uuid4(), "attempts": 1, "folder_url": file_url,
                    "phase": "index", "created_by": "recruiter",
                    "entries": [{"candidate_id": "CAND_0001", "object_id": "resume_123"}]}

        def record_identity(self, *args, **kwargs):
            self.identity = (args, kwargs)

        def record_result(self, job_id, attempt, failure):
            self.result = failure

        def finish(self, job_id, attempt, discovered, skipped):
            assert (discovered, skipped) == (1, 0)

    monkeypatch.setattr(indexing_worker, "token_file", lambda actor: Path("recruiter-token.json"))
    monkeypatch.setattr(indexing_worker, "configured_drive_source", lambda **kwargs: Source())
    jobs = Jobs()
    assert IndexingWorker(jobs, Pipeline()).run_once()
    assert jobs.result is None
    assert jobs.identity[1] == {"source_kind": "drive"}


def test_drive_oauth_callback_requires_same_browser_and_one_use_state(monkeypatch):
    saved = {}
    completed = []

    class OAuth:
        def __init__(self, settings):
            pass

        def authorization_url(self, state, verifier, nonce):
            return f"https://accounts.google.com/auth?state={state}"

        def complete(self, state, verifier, nonce, code, token_file):
            completed.append(code)

    class Jobs:
        def save_drive_oauth_state(self, digest, actor, verifier, nonce):
            saved[digest] = {"actor": actor, "code_verifier": verifier, "nonce": nonce}

        def consume_drive_oauth_state(self, digest):
            return saved.pop(digest, None)

    monkeypatch.setattr(drive_api, "DriveWebOAuth", OAuth)
    monkeypatch.setattr(drive_api, "token_file", lambda actor: Path("recruiter-token.json"))
    app = FastAPI()
    app.state.recruiter_identity = FakeRecruiterIdentity({"secret": "recruiter", "other": "other-recruiter"})
    app.state.index_store = Jobs()
    app.include_router(drive_api.router)
    with TestClient(app) as client:
        client.cookies.set("sieve_recruiter_session", "secret")
        response = client.get("/api/sources/drive/connect", follow_redirects=False)
        assert response.status_code == 307
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        callback = f"/api/sources/drive/oauth/callback?state={state}&code=authorization-code"
        assert TestClient(app).get(callback).status_code == 400
        result = client.get(callback, follow_redirects=False)
        assert result.status_code == 303
        assert result.headers["location"].endswith("/sources?source=drive&drive=connected")
        assert completed == ["authorization-code"]
        assert client.get(callback).status_code == 400
        second = client.get("/api/sources/drive/connect", follow_redirects=False)
        second_state = parse_qs(urlparse(second.headers["location"]).query)["state"][0]
        client.cookies.set("sieve_recruiter_session", "other")
        swapped = client.get(f"/api/sources/drive/oauth/callback?state={second_state}&code=other-code")
        assert swapped.status_code == 403
        assert completed == ["authorization-code"]
