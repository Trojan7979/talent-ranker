"""Indexing claims must not cross the legacy/current recruiter identity boundary."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from sieve_app.indexing_store import IndexingStore
from sieve_app.indexing_worker import IndexingWorker


def test_indexing_worker_can_limit_claims_to_one_recruiter():
    recruiter = str(uuid4())

    class Jobs:
        def claim_next(self, actor_id):
            assert actor_id == recruiter
            return None

    assert IndexingWorker(Jobs(), object(), actor_id=recruiter).run_once() is False


@pytest.mark.integration
def test_legacy_drive_jobs_do_not_block_signed_in_recruiter_claims():
    database_url = os.getenv("SCREENING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SCREENING_TEST_DATABASE_URL for PostgreSQL integration tests")
    schema = "index_actor_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db/migrations/006_sharepoint_ingestion_jobs.sql"
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')
            cur.execute(migration.read_text(encoding="utf-8"))
        store = IndexingStore(make_conninfo(database_url, options=f"-c search_path={schema}"))
        try:
            folder = "https://drive.google.com/drive/folders/folder1"
            legacy = store.submit(uuid4(), folder, [], "legacy-recruiter")
            recruiter = str(uuid4())
            current = store.submit(uuid4(), folder, [], recruiter)
            claimed = store.claim_next(recruiter)
            assert claimed["id"] == current["id"]
            assert store.claim_next() is None
            assert store.get(legacy["id"], "legacy-recruiter")["status"] == "pending"
        finally:
            store.close()
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
