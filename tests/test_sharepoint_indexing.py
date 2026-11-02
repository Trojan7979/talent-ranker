import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from sieve_app.api import create_app
from tests.auth_support import FakeRecruiterIdentity
from sieve_app.indexing_store import IndexingStore
from sieve_app.indexing_worker import IndexingWorker
from talent_ranker.storage import DriveFile

FOLDER = "https://contoso.sharepoint.com/sites/Recruiting/Shared%20Documents/Resumes"


def test_source_preview_requires_recruiter_and_starts_exact_mapping(monkeypatch):
    from sieve_app import source_api

    class Source:
        def list_resumes(self, url):
            assert url == FOLDER
            return [DriveFile("item-1", "CAND_0001.pdf", size=10)]

    class Jobs:
        def submit(self, request_id, folder_url, entries, actor):
            assert folder_url == FOLDER
            assert entries == [{"candidate_id": "CAND_0001", "object_id": "item-1"}]
            assert actor == "recruiter"
            return {"id": uuid4(), "status": "pending", "entries": entries,
                    "discovered": 0, "indexed": 0, "skipped": 0, "failures": []}

        def submit_analysis(self, request_id, folder_url, actor):
            assert folder_url == FOLDER and actor == "recruiter"
            return {"id": uuid4(), "status": "pending", "entries": [],
                    "discovered": 0, "indexed": 0, "skipped": 0, "failures": []}

        def approve(self, job_id, actor, decisions):
            assert actor == "recruiter"
            assert decisions[0]["action"] == "new"
            return {"id": job_id, "status": "pending",
                    "entries": [{"candidate_id": "CAND_0002", "object_id": "item-1"}],
                    "discovered": 0, "indexed": 0, "skipped": 0, "failures": []}

    monkeypatch.setattr(source_api, "_configured", lambda: None)
    monkeypatch.setattr(source_api, "configured_sharepoint_source", lambda settings: Source())
    ranking = FastAPI()
    screening = FastAPI()
    screening.state.settings = SimpleNamespace(recruiter_tokens={"secret": "recruiter"})
    app = create_app(ranking, screening, index_store=Jobs())
    app.state.recruiter_identity = FakeRecruiterIdentity()
    with TestClient(app) as client:
        assert client.post("/api/sources/sharepoint/preview", json={"folder_url": FOLDER}).status_code == 401
        headers = {"Cookie": "sieve_recruiter_session=secret"}
        preview = client.post("/api/sources/sharepoint/preview", headers=headers,
                              json={"folder_url": FOLDER})
        assert preview.status_code == 200, preview.text
        assert preview.json()["files"][0]["file_id"] == "item-1"
        response = client.post("/api/sources/sharepoint/jobs", headers=headers, json={
            "request_id": str(uuid4()), "folder_url": FOLDER,
            "entries": [{"candidate_id": "CAND_0001", "object_id": "item-1"}],
        })
        assert response.status_code == 202, response.text
        assert response.json()["requested"] == 1
        analysis = client.post("/api/sources/sharepoint/analyze", headers=headers, json={
            "request_id": str(uuid4()), "folder_url": FOLDER,
        })
        assert analysis.status_code == 202, analysis.text
        approved = client.post(
            f"/api/sources/sharepoint/jobs/{analysis.json()['id']}/approve",
            headers=headers, json={"decisions": [{"object_id": "item-1", "action": "new"}]},
        )
        assert approved.status_code == 202, approved.text


@pytest.mark.integration
def test_indexing_job_is_idempotent_and_expired_lease_resumes():
    database_url = os.getenv("SCREENING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SCREENING_TEST_DATABASE_URL for PostgreSQL integration tests")
    schema = "index_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db/migrations/006_sharepoint_ingestion_jobs.sql"
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')
            cur.execute(migration.read_text(encoding="utf-8"))
        store = IndexingStore(make_conninfo(database_url, options=f"-c search_path={schema}"))
        try:
            request_id = uuid4()
            entries = [{"candidate_id": "CAND_0001", "object_id": "item-1"}]
            first = store.submit(request_id, FOLDER, entries, "recruiter")
            assert store.submit(request_id, FOLDER, entries, "recruiter")["id"] == first["id"]
            with pytest.raises(ValueError, match="different indexing job"):
                store.submit(request_id, FOLDER, [], "recruiter")
            assert store.get(first["id"], "someone-else") is None
            claimed = store.claim_next()
            assert claimed["id"] == first["id"]
            assert store.claim_next() is None
            store.record_result(first["id"], claimed["attempts"], None)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sharepoint_ingestion_jobs SET leased_until=now()-interval '1 minute' "
                    "WHERE id=%s", (first["id"],)
                )
            resumed = store.claim_next()
            assert resumed["attempts"] == 2
            assert resumed["indexed"] == 0
            with pytest.raises(RuntimeError, match="lease was lost"):
                store.record_result(first["id"], claimed["attempts"], None)
            store.record_result(first["id"], resumed["attempts"], None)
            store.finish(first["id"], resumed["attempts"], discovered=2, skipped=1)
            finished = store.get(first["id"], "recruiter")
            assert (finished["status"], finished["indexed"], finished["skipped"]) == (
                "completed", 1, 1,
            )
        finally:
            store.close()
            with conn.cursor() as cur:
                cur.execute("SET search_path TO public")
                cur.execute(f'DROP SCHEMA "{schema}" CASCADE')


def test_worker_reuses_existing_pipeline_and_records_progress(monkeypatch):
    from sieve_app import indexing_worker

    class Source:
        def list_resumes(self, folder):
            assert folder == FOLDER
            return [DriveFile("item-1", "resume.pdf")]

        def download(self, object_id, destination):
            assert object_id == "item-1"
            destination.write_bytes(b"%PDF mock")

        def source_uri(self, object_id):
            return f"sharepoint://drive-1/{object_id}"

    class Pipeline:
        def ingest_resume(self, candidate_id, path, source_uri, metadata, scope=None):
            assert candidate_id == "CAND_0001"
            assert path.read_bytes() == b"%PDF mock"
            assert source_uri == "sharepoint://drive-1/item-1"
            assert metadata["client_source_uri"] == "sharepoint://drive-1/item-1"
            assert metadata["job_title"] == "Reviewed role"
            assert scope.actor_id == "recruiter"

    class Jobs:
        def __init__(self):
            self.results = []
            self.finished = None

        def claim_next(self):
            return {"id": uuid4(), "folder_url": FOLDER,
                    "phase": "index", "created_by": "recruiter",
                    "attempts": 1,
                    "entries": [{"candidate_id": "CAND_0001", "object_id": "item-1",
                                 "job_title": "Reviewed role"}]}

        def record_identity(self, job_id, attempt, candidate_id, source_uri, name, email, actor):
            assert candidate_id == "CAND_0001"
            assert source_uri == "sharepoint://drive-1/item-1"
            assert actor == "recruiter"

        def record_result(self, job_id, attempt, failure):
            assert attempt == 1
            self.results.append((job_id, failure))

        def finish(self, job_id, attempt, discovered, skipped):
            assert attempt == 1
            self.finished = (job_id, discovered, skipped)

    monkeypatch.setattr(indexing_worker, "configured_sharepoint_source", lambda settings: Source())
    jobs = Jobs()
    assert IndexingWorker(jobs, Pipeline()).run_once()
    assert jobs.results[0][1] is None
    assert jobs.finished[1:] == (1, 0)

    class FailingPipeline(Pipeline):
        def ingest_resume(self, candidate_id, path, source_uri, metadata):
            raise ValueError("sensitive resume text or signed download URL")

    failed_jobs = Jobs()
    assert IndexingWorker(failed_jobs, FailingPipeline()).run_once()
    assert failed_jobs.results[0][1] == "CAND_0001: indexing failed; check worker logs"


def test_worker_analyzes_before_any_embedding_or_indexing(monkeypatch):
    from sieve_app import indexing_worker

    class Source:
        def list_resumes(self, folder):
            return [DriveFile("item-1", "jane.pdf", web_url=FOLDER + "/jane.pdf")]

        def download(self, object_id, destination):
            destination.write_bytes(b"%PDF mock")

        def source_uri(self, object_id):
            return f"sharepoint://drive/{object_id}"

    class Jobs:
        def claim_next(self):
            return {"id": uuid4(), "phase": "analyze", "folder_url": FOLDER,
                    "attempts": 1}

        def match_candidates(self, drafts):
            drafts[0]["suggestion"] = "new"
            return drafts

        def save_analysis(self, job_id, attempt, drafts):
            assert drafts[0]["name"] == "Jane Doe"
            assert drafts[0]["email"] == "jane@example.com"
            assert drafts[0]["job_title"] == "Software Engineer"
            assert drafts[0]["web_url"] == FOLDER + "/jane.pdf"
            self.saved = drafts

    class Pipeline:
        def ingest_resume(self, *_):
            raise AssertionError("analysis must not index")

    monkeypatch.setattr(indexing_worker, "configured_sharepoint_source", lambda settings: Source())
    monkeypatch.setattr(indexing_worker, "extract_resume",
                        lambda path: "Jane Doe\njane@example.com\nRole: Software Engineer\nExperience\n")
    jobs = Jobs()
    assert IndexingWorker(jobs, Pipeline()).run_once()
    assert jobs.saved[0]["source_uri"] == "sharepoint://drive/item-1"
