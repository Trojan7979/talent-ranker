import os
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from candidate_screening.api import create_app
from candidate_screening.config import Settings
from candidate_screening.repository import PostgresRepository

PROFILE_ID = UUID("11111111-1111-1111-1111-111111111111")
RUN_ID = UUID("22222222-2222-2222-2222-222222222222")


class TransactionRepository(PostgresRepository):
    """Run real repository SQL inside one test transaction, rolled back afterward."""

    def __init__(self, conn):
        self.test_conn = conn

    @contextmanager
    def connection(self):
        yield self.test_conn


@pytest.fixture
def client():
    database_url = os.getenv("SCREENING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SCREENING_TEST_DATABASE_URL for rolled-back Postgres API tests")
    schema_name = "screening_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA "{schema_name}"')
                cur.execute(f'SET LOCAL search_path TO "{schema_name}", public')
                cur.execute(
                    "CREATE TABLE candidates (candidate_id text PRIMARY KEY, deleted_at timestamptz)"
                )
                cur.execute("CREATE TABLE jobs (job_id text PRIMARY KEY)")
                cur.execute(
                    """CREATE TABLE job_profile_versions
                       (profile_version_id uuid PRIMARY KEY, job_id text, status text)"""
                )
                cur.execute(
                    """CREATE TABLE ranking_runs
                       (run_id uuid PRIMARY KEY, job_id text,
                        job_profile_version_id uuid, created_at timestamptz DEFAULT now())"""
                )
                cur.execute(
                    """CREATE TABLE ranking_results
                       (run_id uuid, candidate_id text, rank integer, score double precision)"""
                )
                cur.execute(migration.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO jobs VALUES ('job-1')")
                cur.execute(
                    "INSERT INTO job_profile_versions VALUES (%s,'job-1','approved')", (PROFILE_ID,)
                )
                cur.execute(
                    """INSERT INTO ranking_runs(run_id,job_id,job_profile_version_id)
                       VALUES (%s,'job-1',%s)""",
                    (RUN_ID, PROFILE_ID),
                )
                cur.execute(
                    """INSERT INTO candidates VALUES
                       ('CAND_0001',NULL),('CAND_0002',now()),('CAND_0003',NULL)"""
                )
                cur.execute(
                    """INSERT INTO ranking_results VALUES
                       (%s,'CAND_0001',1,0.9),(%s,'CAND_0002',2,0.8),
                       (%s,'CAND_0003',3,0.7)""",
                    (RUN_ID, RUN_ID, RUN_ID),
                )
            app = create_app(
                repository=TransactionRepository(conn),
                settings=Settings(recruiter_tokens={"test-token": "recruiter-1"}),
            )
            with TestClient(app) as test_client:
                yield test_client
        finally:
            conn.rollback()


def headers():
    return {"Authorization": "Bearer test-token"}


def make_config(client):
    response = client.post(
        "/screening/jobs/job-1/configs",
        headers=headers(),
        json={
            "job_profile_version_id": str(PROFILE_ID),
            "questions": {"version": 1, "must_haves": [{"id": "python", "text": "Python"}]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]
