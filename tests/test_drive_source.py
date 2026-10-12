from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sieve_app import drive_api, indexing_worker
from sieve_app.indexing_worker import IndexingWorker
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

    monkeypatch.setattr(drive_api, "_drive_ready", lambda: None)
    monkeypatch.setattr(drive_api, "configured_drive_source", Source)
    app = FastAPI()
    app.state.screening_settings = SimpleNamespace(recruiter_tokens={"secret": "recruiter"})
    app.state.index_store = Jobs()
    app.include_router(drive_api.router)
    with TestClient(app) as client:
        assert client.post("/api/sources/drive/preview", json={"location": file_url}).status_code == 401
        headers = {"Authorization": "Bearer secret"}
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
        def ingest_resume(self, candidate_id, path, source_uri, metadata):
            assert candidate_id == "CAND_0001"
            assert path.suffix == ".pdf"
            assert source_uri == metadata["client_source_uri"] == "gdrive://resume_123"

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

    monkeypatch.setattr(indexing_worker, "configured_drive_source", Source)
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

        def complete(self, state, verifier, nonce, code):
            completed.append(code)

    class Jobs:
        def save_drive_oauth_state(self, digest, actor, verifier, nonce):
            saved[digest] = {"actor": actor, "code_verifier": verifier, "nonce": nonce}

        def consume_drive_oauth_state(self, digest):
            return saved.pop(digest, None)

    monkeypatch.setattr(drive_api, "DriveWebOAuth", OAuth)
    app = FastAPI()
    app.state.screening_settings = SimpleNamespace(recruiter_tokens={"secret": "recruiter"})
    app.state.index_store = Jobs()
    app.include_router(drive_api.router)
    with TestClient(app) as client:
        response = client.post("/api/sources/drive/connect", json={},
                               headers={"Authorization": "Bearer secret"})
        assert response.status_code == 200
        state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
        callback = f"/api/sources/drive/oauth/callback?state={state}&code=authorization-code"
        assert TestClient(app).get(callback).status_code == 400
        result = client.get(callback, follow_redirects=False)
        assert result.status_code == 303
        assert result.headers["location"].endswith("/sources?source=drive&drive=connected")
        assert completed == ["authorization-code"]
        assert client.get(callback).status_code == 400
