"""Legacy and source-backed records resolve without rebuilding their chunks."""

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from sieve_app.indexing_store import IndexingStore


@pytest.mark.integration
def test_source_lookup_supports_legacy_copies_and_filters_deleted_candidates():
    database_url = os.getenv("SCREENING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set SCREENING_TEST_DATABASE_URL for PostgreSQL integration tests")
    schema = "source_test_" + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            conn.execute("""CREATE TABLE candidates (
                candidate_id text PRIMARY KEY, source_uri text NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{}'::jsonb, deleted_at timestamptz)""")
            conn.execute("""INSERT INTO candidates VALUES
                ('CAND_0001','s3://old/resume.pdf',
                 '{"client_source_uri":"sharepoint://Drive/Old","source_etag":"v1"}',NULL),
                ('CAND_0002','sharepoint://Drive/New','{}',NULL),
                ('CAND_0003','sharepoint://Drive/Deleted','{}',now()),
                ('CAND_0004','file:///local/resume.pdf','{}',NULL)""")
            store = IndexingStore(make_conninfo(database_url, options=f"-c search_path={schema}"))
            try:
                assert store.get_candidate_source("CAND_0001") == {
                    "source_uri": "sharepoint://Drive/Old", "source_etag": "v1",
                    "source_md5_checksum": None,
                }
                assert store.get_candidate_source("CAND_0002") == {
                    "source_uri": "sharepoint://Drive/New", "source_etag": None,
                    "source_md5_checksum": None,
                }
                assert store.get_candidate_source("CAND_0003") is None
                assert store.get_candidate_source("CAND_0004")["source_uri"] == "file:///local/resume.pdf"
                assert store.get_candidate_source("CAND_9000") is None
            finally:
                store.close()
        finally:
            conn.execute("SET search_path TO public")
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
