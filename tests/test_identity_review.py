import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from sieve_app.indexing_store import IndexingStore

FOLDER = "https://contoso.sharepoint.com/sites/Recruiting/Shared%20Documents/Resumes"

@pytest.mark.integration
def test_identity_review_reuses_matches_and_reserves_new_ids():
    database_url = os.getenv("SCREENING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SCREENING_TEST_DATABASE_URL for PostgreSQL integration tests")
    schema = "identity_test_" + uuid4().hex
    migrations = Path(__file__).resolve().parents[1] / "db/migrations"
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')
            cur.execute("""CREATE TABLE candidates (
                candidate_id text PRIMARY KEY, source_sha256 text UNIQUE NOT NULL,
                deleted_at timestamptz)""")
            cur.execute("""CREATE TABLE screening_contacts (
                candidate_id text PRIMARY KEY REFERENCES candidates(candidate_id),
                email text NOT NULL, source text NOT NULL, source_reference text,
                contactable boolean NOT NULL, updated_by text NOT NULL)""")
            cur.execute((migrations / "006_sharepoint_ingestion_jobs.sql").read_text())
            cur.execute((migrations / "007_sharepoint_identity_review.sql").read_text())
            cur.execute("INSERT INTO candidates VALUES ('CAND_0001','hash-one',NULL),"
                        "('CAND_0002','hash-two',NULL)")
            cur.execute("""INSERT INTO screening_contacts VALUES
                ('CAND_0001','one@example.com','manual',NULL,true,'recruiter'),
                ('CAND_0002','two@example.com','manual',NULL,true,'recruiter')""")
        store = IndexingStore(make_conninfo(database_url, options=f"-c search_path={schema}"))
        try:
            drafts = store.match_candidates([
                {"object_id": "old", "source_uri": "sharepoint://drive/old",
                 "sha256": "hash-one", "email": None, "name": "One", "file_name": "one.pdf"},
                {"object_id": "email", "source_uri": "sharepoint://drive/email",
                 "sha256": "other", "email": "two@example.com", "name": "Two",
                 "file_name": "two.pdf"},
                {"object_id": "new", "source_uri": "sharepoint://drive/new",
                 "sha256": "new-hash", "email": "new@example.com", "name": "New",
                 "file_name": "new.pdf"},
                {"object_id": "conflict", "source_uri": "sharepoint://drive/conflict",
                 "sha256": "hash-one", "email": "two@example.com", "name": "Unknown",
                 "file_name": "conflict.pdf"},
            ])
            assert [item["suggestion"] for item in drafts] == [
                "existing", "existing", "new", "review",
            ]
            duplicates = store.match_candidates([
                {"object_id": "a", "source_uri": "sharepoint://drive/a",
                 "sha256": "duplicate-bytes", "email": "same@example.com"},
                {"object_id": "b", "source_uri": "sharepoint://drive/b",
                 "sha256": "duplicate-bytes", "email": "same@example.com"},
            ])
            assert [item["suggestion"] for item in duplicates] == ["new", "review"]
            job = store.submit_analysis(uuid4(), FOLDER, "recruiter")
            claimed = store.claim_next()
            assert claimed["phase"] == "analyze"
            store.save_analysis(job["id"], claimed["attempts"], drafts)
            with pytest.raises(ValueError, match="exact file match cannot be reassigned"):
                store.approve(job["id"], "recruiter", [
                    {"object_id": key, "action": "existing", "candidate_id": "CAND_0002"}
                    if key == "old" else {"object_id": key, "action": "skip"}
                    for key in ("old", "email", "new", "conflict")
                ])
            approved = store.approve(job["id"], "recruiter", [
                {"object_id": "old", "action": "skip"},
                {"object_id": "email", "action": "existing", "candidate_id": "CAND_0002",
                 "name": "Two", "email": "two@example.com"},
                {"object_id": "new", "action": "new", "name": "New",
                 "email": "new@example.com", "job_title": "Reviewed title"},
                {"object_id": "conflict", "action": "skip"},
            ])
            assert approved["phase"] == "index"
            assert approved["entries"][1]["job_title"] == "Reviewed title"
            assert [item["candidate_id"] for item in approved["entries"]] == [
                "CAND_0002", "CAND_0003",
            ]
            indexing = store.claim_next()
            assert (indexing["id"], indexing["phase"], indexing["attempts"]) == (
                job["id"], "index", 2,
            )
            second = store.submit_analysis(uuid4(), FOLDER, "recruiter")
            second_claim = store.claim_next()
            store.save_analysis(second["id"], second_claim["attempts"], [drafts[2]])
            second_approved = store.approve(second["id"], "recruiter", [
                {"object_id": "new", "action": "new", "name": "New"},
            ])
            assert second_approved["entries"][0]["candidate_id"] == "CAND_0004"
            with conn.cursor() as cur:
                cur.execute("INSERT INTO candidates VALUES ('CAND_0003','new-hash',NULL)")
            store.record_identity(job["id"], indexing["attempts"], "CAND_0003",
                                  "sharepoint://drive/new",
                                  "New", "new@example.com", "recruiter")
            store.record_result(job["id"], indexing["attempts"], None)
            store.finish(job["id"], indexing["attempts"], discovered=4, skipped=2)
            assert all("email" not in item and "name" not in item
                       for item in store.get(job["id"], "recruiter")["entries"])
            with conn.cursor() as cur:
                cur.execute("SELECT email,contactable FROM screening_contacts "
                            "WHERE candidate_id='CAND_0003'")
                assert cur.fetchone() == ("new@example.com", False)
            updated_file = store.match_candidates([{
                "object_id": "new", "source_uri": "sharepoint://drive/new",
                "sha256": "updated-pdf", "email": None,
            }])[0]
            assert (updated_file["candidate_id"], updated_file["suggestion"]) == (
                "CAND_0003", "existing",
            )
        finally:
            store.close()
            with conn.cursor() as cur:
                cur.execute("SET search_path TO public")
                cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
