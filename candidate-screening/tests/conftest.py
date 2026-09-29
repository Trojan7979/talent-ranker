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
                       (profile_version_id uuid PRIMARY KEY, job_id text, status text,
                        priorities jsonb NOT NULL)"""
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
                cur.execute(
                    (migration.parent / "migrations" / "002_uncertain_delivery.sql").read_text(
                        encoding="utf-8"
                    )
                )
                cur.execute("INSERT INTO jobs VALUES ('job-1')")
                cur.execute(
                    """INSERT INTO job_profile_versions VALUES
                       (%s,'job-1','approved','{"must_have_skills":["Python"]}')""",
                    (PROFILE_ID,),
                )
                cur.execute(
                    """INSERT INTO ranking_runs(run_id,job_id,job_profile_version_id)
                       VALUES (%s,'job-1',%s)""",
                    (RUN_ID, PROFILE_ID),
                )
                cur.execute(
                    """INSERT INTO candidates VALUES
                       ('CAND_0001',NULL),('CAND_0002',now()),('CAND_0003',NULL),
                       ('CAND_0004',NULL),('CAND_0005',NULL)"""
                )
                cur.execute(
                    """INSERT INTO ranking_results VALUES
                       (%s,'CAND_0001',1,0.9),(%s,'CAND_0002',2,0.8),
                       (%s,'CAND_0003',3,0.7),(%s,'CAND_0004',4,0.6),
                       (%s,'CAND_0005',5,0.5)""",
                    (RUN_ID, RUN_ID, RUN_ID, RUN_ID, RUN_ID),
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


def sent_invite(client):
    from candidate_screening.delivery import InitialInviteDispatcher
    from candidate_screening.email import FakeEmailSender

    config_id = make_config(client)
    contact = client.put(
        "/screening/candidates/CAND_0001/contact",
        headers=headers(),
        json={"email": "candidate@example.test", "source": "ats"},
    )
    assert contact.status_code == 200
    proposal = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            "job_id": "job-1",
            "ranking_run_id": str(RUN_ID),
            "config_id": config_id,
            "rule": {"kind": "top_n", "value": 1},
            "message_template": "Hello {screening_link}",
        },
    )
    assert proposal.status_code == 201, proposal.text
    campaign_id = proposal.json()["id"]
    approval = client.post(
        f"/screening/campaigns/{campaign_id}/approve",
        headers=headers(),
        json={"expected_revision": 1},
    )
    assert approval.status_code == 200, approval.text
    sender = FakeEmailSender()
    assert InitialInviteDispatcher(client.app.state.repo, sender).run_once()["sent"] == 1
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT token FROM screening_invites WHERE campaign_id=%s", (campaign_id,))
        token = cur.fetchone()["token"]
    return campaign_id, token
