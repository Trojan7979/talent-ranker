"""Saved shortlist pagination against the upstream Postgres schema."""

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import HTTPException

from talent_ranker.access import RecruiterScope
from talent_ranker.api import (
    app,
    get_candidate_evidence,
    get_saved_ranking_run,
    list_saved_ranking_runs,
)
from talent_ranker.repository import PostgresRepository

RUN_ID = UUID("66666666-6666-6666-6666-666666666666")
PROFILE_ID = UUID("55555555-5555-5555-5555-555555555555")


def test_saved_run_pages_skip_deleted_candidates_and_keep_rank_cursor():
    url = os.getenv("TALENT_RANKER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TALENT_RANKER_TEST_DATABASE_URL for Postgres contract test")
    schema = "saved_run_test_" + uuid4().hex
    migration = Path(__file__).resolve().parents[1] / "db/schema.sql"
    with psycopg.connect(url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA "{schema}"')
                cur.execute(f'SET LOCAL search_path TO "{schema}", public')
                cur.execute(migration.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO jobs(job_id,job_description) VALUES ('job-1','Mock role')")
                cur.execute(
                    """INSERT INTO job_profile_versions
                       (profile_version_id,job_id,version,job_description,priorities)
                       VALUES (%s,'job-1',1,'Mock role','{}')""",
                    (PROFILE_ID,),
                )
                cur.execute(
                    """INSERT INTO ranking_runs
                       (run_id,job_id,job_profile_version_id,jd_text,model_versions,scoring_config,
                        workspace_id,actor_id)
                       VALUES (%s,'job-1',%s,'Mock role','{}','{}','demo','alex')""",
                    (RUN_ID, PROFILE_ID),
                )
                cur.execute(
                    """INSERT INTO candidates
                       (candidate_id,source_uri,source_sha256,raw_text,deleted_at)
                       VALUES ('CAND_0001','mock://1','hash1','one',NULL),
                              ('CAND_0002','mock://2','hash2','two',now()),
                              ('CAND_0003','mock://3','hash3','three',NULL)"""
                )
                cur.execute(
                    """INSERT INTO ranking_results
                       (run_id,candidate_id,rank,score,score_components,evidence,reasoning)
                       VALUES (%s,'CAND_0001',1,0.9,'{}','[]','first'),
                              (%s,'CAND_0002',2,0.8,'{}','[]','deleted'),
                              (%s,'CAND_0003',3,0.7,'{}','[]','third')""",
                    (RUN_ID, RUN_ID, RUN_ID),
                )
                cur.execute(
                    """INSERT INTO candidate_source_grants
                       (candidate_id,workspace_id,actor_id,source_uri,grant_kind)
                       VALUES ('CAND_0001','demo','alex','mock://1','owner'),
                              ('CAND_0002','demo','alex','mock://2','owner'),
                              ('CAND_0003','demo','alex','mock://3','owner')"""
                )
            repo = PostgresRepository.__new__(PostgresRepository)
            repo.conn = conn
            app.state.pipeline = SimpleNamespace(repo=repo)
            access = RecruiterScope("demo", "alex", frozenset({"job-1"}))
            first = get_saved_ranking_run(RUN_ID, access, after_rank=0, limit=1)
            second = get_saved_ranking_run(RUN_ID, access, after_rank=first.next_after_rank, limit=1)
            assert first.total_count == 2
            assert first.job_profile_version_id == PROFILE_ID
            assert [item.candidate_id for item in first.items] == ["CAND_0001"]
            assert first.next_after_rank == 1
            assert [item.candidate_id for item in second.items] == ["CAND_0003"]
            assert second.next_after_rank is None

            created_at = datetime(2026, 9, 29, tzinfo=UTC)
            newer_id = UUID("77777777-7777-7777-7777-777777777777")
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ranking_runs SET created_at=%s WHERE run_id=%s",
                    (created_at, RUN_ID),
                )
                cur.execute(
                    """INSERT INTO ranking_runs
                       (run_id,job_id,job_profile_version_id,jd_text,model_versions,
                        scoring_config,created_at,workspace_id,actor_id)
                       VALUES (%s,'job-1',%s,'Mock role','{}','{}',%s,'demo','alex')""",
                    (newer_id, PROFILE_ID, created_at),
                )
            directory = list_saved_ranking_runs(access, None, None, None, 1)
            assert [item.run_id for item in directory.items] == [newer_id]
            assert directory.items[0].total_count == 0
            older = list_saved_ranking_runs(
                access, "job-1", directory.next_before_created_at, directory.next_before_run_id, 1
            )
            assert [item.run_id for item in older.items] == [RUN_ID]
            assert older.items[0].total_count == 2
            assert older.next_before_run_id is None
            with pytest.raises(HTTPException) as forbidden:
                list_saved_ranking_runs(access, "other-job", None, None, 1)
            assert forbidden.value.status_code == 404
            with pytest.raises(HTTPException) as error:
                get_saved_ranking_run(uuid4(), access, after_rank=0, limit=1)
            assert error.value.status_code == 404
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM candidate_source_grants WHERE candidate_id='CAND_0001'"
                )
            visible = get_saved_ranking_run(RUN_ID, access, after_rank=0, limit=5)
            assert [item.candidate_id for item in visible.items] == ["CAND_0003"]
            with pytest.raises(HTTPException) as revoked:
                get_candidate_evidence(RUN_ID, "CAND_0001", access)
            assert revoked.value.status_code == 404
        finally:
            conn.rollback()


def test_saved_run_directory_requires_both_cursor_fields():
    with pytest.raises(HTTPException) as error:
        list_saved_ranking_runs(
            RecruiterScope("demo", "alex", frozenset({"job-1"})),
            None, datetime(2026, 9, 29, tzinfo=UTC), None, 25,
        )
    assert error.value.status_code == 422
