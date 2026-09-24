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
        pytest.skip("set SCREENING_TEST_DATABASE_URL for proposal integration tests")
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
                    "INSERT INTO ranking_runs(run_id,job_id,job_profile_version_id) VALUES (%s,'job-1',%s)",
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


@pytest.mark.integration
def test_proposals_pin_run_and_never_send(client):
    assert client.post("/screening/selections", json={}).status_code == 401
    config_id = make_config(client)
    contact = client.put(
        "/screening/candidates/CAND_0001/contact",
        headers=headers(),
        json={"email": "person@example.test", "source": "ats"},
    )
    assert contact.status_code == 200, contact.text
    request = {
        "job_id": "job-1",
        "ranking_run_id": str(RUN_ID),
        "rule": {"kind": "top_n", "value": 2},
    }
    preview = client.post("/screening/selections", headers=headers(), json=request)
    assert preview.status_code == 200, preview.text
    assert [item["candidate_id"] for item in preview.json()["candidates"]] == [
        "CAND_0001",
        "CAND_0003",
    ]
    assert [item["has_contact"] for item in preview.json()["candidates"]] == [True, False]
    proposed = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={**request, "config_id": config_id, "message_template": "Hello, use {screening_link}"},
    )
    assert proposed.status_code == 201, proposed.text
    campaign = proposed.json()
    assert campaign["status"] == "proposed"
    assert campaign["proposed_candidate_ids"] == ["CAND_0001", "CAND_0003"]
    with client.app.state.repo.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS count FROM screening_invites")
        assert cur.fetchone()["count"] == 0
    edited = client.patch(
        f"/screening/campaigns/{campaign['id']}",
        headers=headers(),
        json={
            "expected_revision": 1,
            "final_candidate_ids": ["CAND_0003", "CAND_0001"],
            "message_template": "Hi {screening_link}",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["final_candidate_ids"] == ["CAND_0003", "CAND_0001"]
    assert (
        client.patch(
            f"/screening/campaigns/{campaign['id']}",
            headers=headers(),
            json={
                "expected_revision": 1,
                "final_candidate_ids": ["CAND_0001"],
                "message_template": "Hi {screening_link}",
            },
        ).status_code
        == 409
    )
    rejected = client.post(
        f"/screening/campaigns/{campaign['id']}/reject?expected_revision=2", headers=headers()
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


@pytest.mark.integration
def test_selector_boundaries_and_invalid_membership(client):
    config_id = make_config(client)
    base = {"job_id": "job-1", "ranking_run_id": str(RUN_ID)}
    for rule, expected in [
        ({"kind": "score_threshold", "value": 0.8}, ["CAND_0001"]),
        ({"kind": "rank_cutoff", "value": 2}, ["CAND_0001"]),
        ({"kind": "top_n", "value": 2}, ["CAND_0001", "CAND_0003"]),
    ]:
        response = client.post(
            "/screening/selections", headers=headers(), json={**base, "rule": rule}
        )
        assert response.status_code == 200, response.text
        assert [item["candidate_id"] for item in response.json()["candidates"]] == expected
    proposed = client.post(
        "/screening/campaigns",
        headers=headers(),
        json={
            **base,
            "rule": {"kind": "top_n", "value": 2},
            "config_id": config_id,
            "message_template": "Hi {screening_link}",
        },
    ).json()
    invalid = client.patch(
        f"/screening/campaigns/{proposed['id']}",
        headers=headers(),
        json={
            "expected_revision": 1,
            "final_candidate_ids": ["CAND_0002"],
            "message_template": "Hi {screening_link}",
        },
    )
    assert invalid.status_code == 409
