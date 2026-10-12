"""Run against an explicit test DB; every test owns an isolated schema."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from talent_ranker.external_evidence import EvidenceStore, sync_resume_links
from talent_ranker.resume_links import ResumeLink

pytestmark = pytest.mark.integration
LINK = ResumeLink('https://github.com/alex/work', 'github', 'hyperlink')


@pytest.fixture
def database():
    url = os.getenv('SCREENING_TEST_DATABASE_URL')
    if not url:
        pytest.skip('set SCREENING_TEST_DATABASE_URL to run PostgreSQL evidence tests')
    schema = 'evidence_test_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        conn.execute('''CREATE TABLE candidates(candidate_id text PRIMARY KEY,
                        source_sha256 text NOT NULL, deleted_at timestamptz)''')
        conn.execute("INSERT INTO candidates VALUES ('CAND_0001','v1',NULL)")
        migration = (Path(__file__).resolve().parents[1] /
                     'db/migrations/008_resume_link_evidence.sql').read_text(encoding='utf-8')
        conn.execute(migration)
        conn.execute(migration)
        store = EvidenceStore(make_conninfo(url, options=f'-c search_path={schema}'))
        try:
            yield conn, store
        finally:
            store.close()
            conn.execute('SET search_path TO public')
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def discover(conn, links=(LINK,), version='v1'):
    with conn.transaction(), conn.cursor() as cur:
        cur.execute('UPDATE candidates SET source_sha256=%s WHERE candidate_id=%s',
                    (version, 'CAND_0001'))
        sync_resume_links(cur, 'CAND_0001', version, links)


def test_discovery_is_atomic_and_fresh_evidence_is_reused(database):
    conn, store = database
    with pytest.raises(RuntimeError), conn.transaction(), conn.cursor() as cur:
        sync_resume_links(cur, 'CAND_0001', 'v1', [LINK])
        raise RuntimeError('ingestion failed')
    assert store.get_for_candidates(['CAND_0001']) == {'CAND_0001': []}
    discover(conn)
    discover(conn)
    job = store.claim_next()
    assert job is not None and store.claim_next() is None
    assert store.complete(job, {'text': 'project evidence'})
    before = conn.execute('SELECT xmin::text FROM candidate_external_evidence').fetchone()[0]
    discover(conn)
    after = conn.execute('SELECT xmin::text FROM candidate_external_evidence').fetchone()[0]
    assert before == after  # Re-ingestion must not rewrite a fresh cache row.
    assert store.claim_next() is None
    rows = store.get_for_candidates(['CAND_0001'])['CAND_0001']
    assert len(rows) == 1 and rows[0]['evidence']['text'] == 'project evidence'
    conn.execute("UPDATE candidate_external_evidence SET fetched_at=now()-interval '8 days'")
    discover(conn)
    assert store.claim_next()['attempts'] == 1


def test_batch_read_distinguishes_no_links_missing_deleted_and_replaced_sources(database):
    conn, store = database
    discover(conn)
    conn.execute("INSERT INTO candidates VALUES ('CAND_0002','v1',NULL),"
                 "('CAND_0003','v1',now())")
    results = store.get_for_candidates(['CAND_0001', 'CAND_0002', 'CAND_0003', 'CAND_0004'])
    assert set(results) == {'CAND_0001', 'CAND_0002'}
    assert len(results['CAND_0001']) == 1 and results['CAND_0002'] == []
    conn.execute("UPDATE candidates SET source_sha256='v2' WHERE candidate_id='CAND_0001'")
    assert store.get_for_candidates(['CAND_0001']) == {'CAND_0001': []}


def test_expired_lease_is_recovered_and_old_result_cannot_overwrite(database):
    conn, store = database
    discover(conn)
    first = store.claim_next()
    conn.execute("UPDATE candidate_external_evidence SET leased_until=now()-interval '1 second'")
    second = store.claim_next()
    assert second['attempts'] == 2 and second['lease_token'] != first['lease_token']
    assert not store.complete(first, {'text': 'stale'})
    assert store.complete(second, {'text': 'current'})


def test_resume_replacement_removes_old_links_and_invalidates_inflight_work(database):
    conn, store = database
    discover(conn)
    old_job = store.claim_next()
    replacement = ResumeLink('https://alex.dev/', 'web', 'text')
    discover(conn, (replacement,), 'v2')
    assert not store.complete(old_job, {'text': 'old resume'})
    rows = store.get_for_candidates(['CAND_0001'])['CAND_0001']
    assert [row['url'] for row in rows] == [replacement.url]
    assert rows[0]['source_sha256'] == 'v2'


def test_queue_retries_are_delayed_bounded_and_deleted_candidates_are_hidden(database):
    conn, store = database
    discover(conn)
    for attempt in range(1, 4):
        job = store.claim_next()
        assert job['attempts'] == attempt
        assert store.fail(job, 'http_429', retryable=True, retry_after=120)
        assert store.claim_next() is None
        conn.execute("UPDATE candidate_external_evidence SET next_attempt_at=now()-interval '1 second'")
    assert store.get_for_candidates(['CAND_0001'])['CAND_0001'][0]['status'] == 'failed'
    conn.execute("UPDATE candidates SET deleted_at=now()")
    assert store.get_for_candidates(['CAND_0001']) == {}
    assert store.claim_next() is None


def test_two_workers_claim_distinct_jobs_and_skip_locked_rows(database):
    conn, store = database
    discover(conn, (LINK, ResumeLink('https://alex.dev/', 'web', 'text')))
    with conn.transaction():
        locked = conn.execute('SELECT id FROM candidate_external_evidence ORDER BY url LIMIT 1 '
                              'FOR UPDATE').fetchone()[0]
        job = store.claim_next()
        assert job['id'] != locked
        assert store.claim_next() is None
    assert store.claim_next()['id'] == locked
