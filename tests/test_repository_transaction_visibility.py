"""A saved profile and run must be visible to the separate screening service."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from talent_ranker.repository import PostgresRepository


def test_profile_approval_and_run_are_committed_for_other_connections():
    url = os.getenv("TALENT_RANKER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TALENT_RANKER_TEST_DATABASE_URL for Postgres contract test")
    schema = "visibility_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db/schema.sql"
    with psycopg.connect(url) as setup:
        setup.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        setup.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema)))
        setup.execute(migration.read_text(encoding="utf-8"))

    isolated_url = make_conninfo(url, options=f"-c search_path={schema},public")
    try:
        repo = PostgresRepository(isolated_url)
        try:
            profile = repo.create_job_profile(
                "job-1", "Mock role", {"must_have_skills": ["Python"]}
            )
            with psycopg.connect(isolated_url, autocommit=True) as observer:
                assert observer.execute(
                    "SELECT status FROM job_profile_versions WHERE profile_version_id=%s",
                    (profile["profile_version_id"],),
                ).fetchone() == ("draft",)

                repo.get_job_profile(profile["profile_version_id"])
                approved = repo.approve_job_profile(profile["profile_version_id"], "recruiter")
                assert approved["status"] == "approved"
                assert observer.execute(
                    "SELECT status FROM job_profile_versions WHERE profile_version_id=%s",
                    (profile["profile_version_id"],),
                ).fetchone() == ("approved",)

                run_id = repo.save_run(
                    "job-1", profile["profile_version_id"], "Mock role", {}, {}, []
                )
                assert observer.execute(
                    "SELECT job_id FROM ranking_runs WHERE run_id=%s", (run_id,)
                ).fetchone() == ("job-1",)
        finally:
            repo.close()
    finally:
        with psycopg.connect(url, autocommit=True) as cleanup:
            cleanup.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
