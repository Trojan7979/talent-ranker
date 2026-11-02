"""A saved profile and run must be visible to the separate screening service."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from talent_ranker.access import RecruiterScope
from talent_ranker.documents import Chunk
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
    scope = RecruiterScope("demo", "recruiter", frozenset({"job-1"}))
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
                    "job-1", profile["profile_version_id"], "Mock role", {}, {}, [], scope
                )
                assert observer.execute(
                    "SELECT job_id FROM ranking_runs WHERE run_id=%s", (run_id,)
                ).fetchone() == ("job-1",)
        finally:
            repo.close()
    finally:
        with psycopg.connect(url, autocommit=True) as cleanup:
            cleanup.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_new_resume_uses_hosted_vector_for_storage_and_retrieval():
    url = os.getenv("TALENT_RANKER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TALENT_RANKER_TEST_DATABASE_URL for Postgres contract test")
    schema = "hosted_vector_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db/schema.sql"
    with psycopg.connect(url) as setup:
        setup.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        setup.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema)))
        setup.execute(migration.read_text(encoding="utf-8"))

    isolated_url = make_conninfo(url, options=f"-c search_path={schema},public")
    scope = RecruiterScope("demo", "recruiter", frozenset({"job-1"}))
    try:
        repo = PostgresRepository(isolated_url)
        try:
            vector = [1.0] + [0.0] * 1023
            repo.upsert_candidate(
                "HOSTED_001", "memory://resume", "test-hash", "Python FastAPI",
                [Chunk(0, 0, "experience", "Python FastAPI", "Python FastAPI")],
                [vector],
                scope=scope,
            )
            repo.assert_embedding_ready(scope)
            with psycopg.connect(isolated_url) as observer:
                dimensions = observer.execute(
                    "SELECT vector_dims(embedding_v2) FROM resume_chunks"
                ).fetchone()[0]
            assert dimensions == 1024
            dense, _, _ = repo.retrieve("Python", vector, 10, scope)
            assert dense == ["HOSTED_001"]
        finally:
            repo.close()
    finally:
        with psycopg.connect(url, autocommit=True) as cleanup:
            cleanup.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_retrieval_filters_before_ranking_and_respects_shared_grants():
    url = os.getenv("TALENT_RANKER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TALENT_RANKER_TEST_DATABASE_URL for Postgres contract test")
    schema = "recruiter_scope_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db/schema.sql"
    with psycopg.connect(url) as setup:
        setup.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        setup.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema)))
        setup.execute(migration.read_text(encoding="utf-8"))
    isolated_url = make_conninfo(url, options=f"-c search_path={schema},public")
    first = RecruiterScope("demo", "recruiter-a", frozenset({"job-1"}))
    second = RecruiterScope("demo", "recruiter-b", frozenset({"job-1"}))
    vector = [1.0] + [0.0] * 1023
    chunk = Chunk(0, 0, "experience", "Python FastAPI", "Python FastAPI")
    try:
        repo = PostgresRepository(isolated_url)
        try:
            repo.upsert_candidate(
                "CAND_A", "memory://a", "hash-a", "Python FastAPI",
                [chunk], [vector], scope=first,
            )
            repo.upsert_candidate(
                "CAND_B", "memory://b", "hash-b", "Python FastAPI",
                [chunk], [vector], scope=second,
            )
            assert repo.retrieve("Python", vector, 10, first)[0] == ["CAND_A"]
            assert repo.retrieve("Python", vector, 10, second)[0] == ["CAND_B"]
            with pytest.raises(PermissionError):
                repo.upsert_candidate(
                    "CAND_A", "memory://a", "hash-a", "Python FastAPI",
                    [chunk], [vector], scope=second,
                )
            repo.conn.execute(
                """INSERT INTO candidate_source_grants
                   (candidate_id,workspace_id,actor_id,source_uri,grant_kind)
                   VALUES ('CAND_A','demo','recruiter-b','memory://a','shared')"""
            )
            assert set(repo.retrieve("Python", vector, 10, second)[0]) == {
                "CAND_A", "CAND_B"
            }
            repo.conn.execute(
                "DELETE FROM candidate_source_grants WHERE candidate_id='CAND_A' AND actor_id='recruiter-b'"
            )
            assert repo.retrieve("Python", vector, 10, second)[0] == ["CAND_B"]
        finally:
            repo.close()
    finally:
        with psycopg.connect(url, autocommit=True) as cleanup:
            cleanup.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
