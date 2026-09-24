"""Exercise the migration without modifying persistent ranking tables."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest


@pytest.mark.integration
def test_screening_schema_constraints_against_minimal_upstream_fixtures() -> None:
    database_url = os.getenv("SCREENING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SCREENING_TEST_DATABASE_URL for rolled-back Postgres schema test")

    schema_name = "screening_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    with psycopg.connect(database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA "{schema_name}"')
                cur.execute(f'SET LOCAL search_path TO "{schema_name}", public')
                cur.execute(
                    "CREATE TABLE candidates (candidate_id text PRIMARY KEY, deleted_at timestamptz)"
                )
                cur.execute("CREATE TABLE jobs (job_id text PRIMARY KEY)")
                cur.execute(
                    "CREATE TABLE job_profile_versions (profile_version_id uuid PRIMARY KEY)"
                )
                cur.execute("CREATE TABLE ranking_runs (run_id uuid PRIMARY KEY)")
                cur.execute(migration.read_text(encoding="utf-8"))

                cur.execute("INSERT INTO candidates(candidate_id) VALUES ('CAND_0001')")
                cur.execute("INSERT INTO jobs(job_id) VALUES ('job-1')")
                cur.execute(
                    """INSERT INTO screening_contacts
                       (candidate_id,email,source,updated_by)
                       VALUES ('CAND_0001','c@example.test','fixture','test')"""
                )
                cur.execute(
                    """INSERT INTO screening_contacts
                       (candidate_id,email,source,updated_by)
                       VALUES ('missing','x@example.test','fixture','test')"""
                )
        except psycopg.errors.ForeignKeyViolation:
            conn.rollback()
        else:
            pytest.fail("contact FK accepted a candidate that does not exist")

        with conn.cursor() as cur:
            cur.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema=%s AND table_name='screening_contacts'""",
                (schema_name,),
            )
            assert cur.fetchone() is None  # the migration rolled back with the failed insert


@pytest.mark.integration
def test_schema_rejects_unknown_outcome_and_duplicate_invites() -> None:
    database_url = os.getenv("SCREENING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SCREENING_TEST_DATABASE_URL for rolled-back Postgres schema test")

    schema_name = "screening_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    with psycopg.connect(database_url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA "{schema_name}"')
                cur.execute(f'SET LOCAL search_path TO "{schema_name}", public')
                cur.execute(
                    "CREATE TABLE candidates (candidate_id text PRIMARY KEY, deleted_at timestamptz)"
                )
                cur.execute("CREATE TABLE jobs (job_id text PRIMARY KEY)")
                cur.execute(
                    "CREATE TABLE job_profile_versions (profile_version_id uuid PRIMARY KEY)"
                )
                cur.execute("CREATE TABLE ranking_runs (run_id uuid PRIMARY KEY)")
                cur.execute(migration.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO candidates(candidate_id) VALUES ('CAND_0001')")
                cur.execute("INSERT INTO jobs(job_id) VALUES ('job-1')")
                cur.execute(
                    "INSERT INTO job_profile_versions VALUES ('11111111-1111-1111-1111-111111111111')"
                )
                cur.execute(
                    "INSERT INTO ranking_runs VALUES ('22222222-2222-2222-2222-222222222222')"
                )
                cur.execute(
                    """INSERT INTO screening_job_configs
                       (job_id,job_profile_version_id,version,questions,created_by)
                       VALUES ('job-1','11111111-1111-1111-1111-111111111111',1,'{}','test')
                       RETURNING id"""
                )
                config_id = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO screening_campaigns
                       (job_id,ranking_run_id,job_profile_version_id,config_id,
                        config_snapshot,selection_rule,proposed_candidate_ids,
                        message_template,expiry_hours)
                       VALUES ('job-1','22222222-2222-2222-2222-222222222222',
                               '11111111-1111-1111-1111-111111111111',
                               %s,'{}','{}',ARRAY['CAND_0001'],'Hello',48)
                       RETURNING id""",
                    (config_id,),
                )
                campaign_id = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO screening_invites(campaign_id,candidate_id,token,expires_at)
                       VALUES (%s,'CAND_0001',repeat('a',43),now()+interval '48 hours')
                       RETURNING id""",
                    (campaign_id,),
                )
                invite_id = cur.fetchone()[0]
                with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
                    cur.execute(
                        """INSERT INTO screening_summary
                               (invite_id,outcome,confirmed,missing,needs_verification,
                                reason_codes,policy_version,config_version)
                               VALUES (%s,'unknown','[]','[]','[]','[]','screening-v1',1)""",
                        (invite_id,),
                    )
                with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
                    cur.execute(
                        """INSERT INTO screening_invites
                               (campaign_id,candidate_id,token,expires_at)
                               VALUES (%s,'CAND_0001',repeat('b',43),now())""",
                        (campaign_id,),
                    )
        finally:
            conn.rollback()
